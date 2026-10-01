// Export a reproducible, instruction-backed corpus for the Nintendo NWM host.
// @category Nintendo3DS

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.HashSet;
import java.util.Set;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;

public class NwmExportFullCorpus extends GhidraScript {
    private static final int DECOMPILE_TIMEOUT_SECONDS = 120;

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1) {
            throw new IllegalArgumentException(
                "usage: NwmExportFullCorpus.java OUTPUT_DIR");
        }

        File output = new File(args[0]);
        File sources = new File(output, "functions");
        File assembly = new File(output, "disassembly");
        mkdirs(output);
        mkdirs(sources);
        mkdirs(assembly);

        PrintWriter functions = writer(output, "functions.tsv");
        PrintWriter calls = writer(output, "calls.tsv");
        PrintWriter strings = writer(output, "strings.tsv");
        PrintWriter refs = writer(output, "string_refs.tsv");
        PrintWriter symbols = writer(output, "symbols.tsv");
        PrintWriter instructions = writer(output, "instructions.tsv");
        PrintWriter failures = writer(output, "failures.tsv");

        functions.println("address\tname\tlength\tcalling_convention\tdecompile_status\tsource_file\tdisassembly_file");
        calls.println("caller_address\tcaller_name\tcallsite\tcallee_address\tcallee_name\treference_type");
        strings.println("address\tvalue");
        refs.println("string_address\tfrom_address\treference_type\tvalue");
        symbols.println("address\tname\tnamespace\tsource_type\tsymbol_type");
        instructions.println("address\tfunction_address\tfunction_name\tbytes\tmnemonic\toperands\tflow_type");
        failures.println("address\tname\terror\tdisassembly_file");

        exportStrings(strings, refs);
        exportSymbols(symbols);

        DecompInterface decompiler = new DecompInterface();
        decompiler.toggleCCode(true);
        decompiler.toggleSyntaxTree(true);
        decompiler.openProgram(currentProgram);

        int functionCount = 0;
        int failureCount = 0;
        FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
        while (iterator.hasNext() && !monitor.isCancelled()) {
            Function function = iterator.next();
            String stem = function.getEntryPoint() + "_" + safe(function.getName());
            File sourceFile = new File(sources, stem + ".c");
            File assemblyFile = new File(assembly, stem + ".txt");

            DecompileResults result = decompiler.decompileFunction(
                function, DECOMPILE_TIMEOUT_SECONDS, monitor);
            String status;
            try (PrintWriter source = writer(sourceFile)) {
                source.println("/* NWM function " + function.getEntryPoint() +
                    " " + function.getName(true) + " */");
                if (result.decompileCompleted() &&
                        result.getDecompiledFunction() != null) {
                    status = "ok";
                    source.println(result.getDecompiledFunction().getC());
                } else {
                    status = "failed";
                    String error = clean(result.getErrorMessage());
                    source.println("/* DECOMPILE FAILED: " + error + " */");
                    failures.println(function.getEntryPoint() + "\t" +
                        clean(function.getName(true)) + "\t" + error + "\t" +
                        relative(output, assemblyFile));
                    failureCount++;
                }
            }

            exportInstructions(function, assemblyFile, instructions, calls);
            functions.println(function.getEntryPoint() + "\t" +
                clean(function.getName(true)) + "\t" +
                function.getBody().getNumAddresses() + "\t" +
                clean(function.getCallingConventionName()) + "\t" + status +
                "\t" + relative(output, sourceFile) + "\t" +
                relative(output, assemblyFile));
            functionCount++;
        }
        decompiler.dispose();

        functions.close();
        calls.close();
        strings.close();
        refs.close();
        symbols.close();
        instructions.close();
        failures.close();

        try (PrintWriter manifest = writer(output, "manifest.txt")) {
            manifest.println("program=" + currentProgram.getName());
            manifest.println("executable_path=" + currentProgram.getExecutablePath());
            manifest.println("executable_sha256=" + currentProgram.getExecutableSHA256());
            manifest.println("language=" + currentProgram.getLanguageID());
            manifest.println("compiler_spec=" + currentProgram.getCompilerSpec().getCompilerSpecID());
            manifest.println("image_base=" + currentProgram.getImageBase());
            manifest.println("memory_min=" + currentProgram.getMinAddress());
            manifest.println("memory_max=" + currentProgram.getMaxAddress());
            manifest.println("functions=" + functionCount);
            manifest.println("decompile_failures=" + failureCount);
        }
        println("NWM full corpus: exported " + functionCount +
            " functions (" + failureCount + " failures) to " + output);
    }

    private void exportStrings(PrintWriter strings, PrintWriter refs) {
        for (Data data : currentProgram.getListing().getDefinedData(true)) {
            Object value = data.getValue();
            if (!(value instanceof String)) {
                continue;
            }
            String text = clean((String)value);
            strings.println(data.getAddress() + "\t" + text);
            for (Reference ref : currentProgram.getReferenceManager()
                    .getReferencesTo(data.getAddress())) {
                refs.println(data.getAddress() + "\t" + ref.getFromAddress() +
                    "\t" + ref.getReferenceType() + "\t" + text);
            }
        }
    }

    private void exportSymbols(PrintWriter out) {
        SymbolIterator iterator = currentProgram.getSymbolTable().getAllSymbols(true);
        while (iterator.hasNext() && !monitor.isCancelled()) {
            Symbol symbol = iterator.next();
            out.println(symbol.getAddress() + "\t" + clean(symbol.getName()) +
                "\t" + clean(symbol.getParentNamespace().getName(true)) + "\t" +
                symbol.getSource() + "\t" + symbol.getSymbolType());
        }
    }

    private void exportInstructions(Function function, File assemblyFile,
            PrintWriter instructionIndex, PrintWriter calls) throws Exception {
        Set<String> emittedCalls = new HashSet<String>();
        try (PrintWriter assembly = writer(assemblyFile)) {
            assembly.println("# " + function.getEntryPoint() + " " +
                function.getName(true));
            InstructionIterator iterator = currentProgram.getListing()
                .getInstructions(function.getBody(), true);
            while (iterator.hasNext() && !monitor.isCancelled()) {
                Instruction instruction = iterator.next();
                String bytes = hex(instruction.getBytes());
                String operands = operands(instruction);
                assembly.println(instruction.getAddress() + "  " + bytes + "  " +
                    instruction.getMnemonicString() +
                    (operands.length() == 0 ? "" : " " + operands));
                instructionIndex.println(instruction.getAddress() + "\t" +
                    function.getEntryPoint() + "\t" + clean(function.getName(true)) +
                    "\t" + bytes + "\t" + instruction.getMnemonicString() + "\t" +
                    clean(operands) + "\t" + instruction.getFlowType());

                if (!instruction.getFlowType().isCall()) {
                    continue;
                }
                boolean referenced = false;
                for (Reference ref : instruction.getReferencesFrom()) {
                    if (!ref.getReferenceType().isCall()) {
                        continue;
                    }
                    referenced = true;
                    Address target = ref.getToAddress();
                    Function callee = currentProgram.getFunctionManager()
                        .getFunctionContaining(target);
                    String calleeName = callee == null ? "" : callee.getName(true);
                    String row = function.getEntryPoint() + "\t" +
                        clean(function.getName(true)) + "\t" + instruction.getAddress() +
                        "\t" + target + "\t" + clean(calleeName) + "\t" +
                        ref.getReferenceType();
                    if (emittedCalls.add(row)) {
                        calls.println(row);
                    }
                }
                if (!referenced) {
                    calls.println(function.getEntryPoint() + "\t" +
                        clean(function.getName(true)) + "\t" + instruction.getAddress() +
                        "\tINDIRECT\t\t" + instruction.getFlowType());
                }
            }
        }
    }

    private String operands(Instruction instruction) {
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < instruction.getNumOperands(); i++) {
            if (i != 0) {
                result.append(", ");
            }
            result.append(instruction.getDefaultOperandRepresentation(i));
        }
        return result.toString();
    }

    private String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder();
        for (byte value : bytes) {
            result.append(String.format("%02x", value & 0xff));
        }
        return result.toString();
    }

    private String clean(String value) {
        if (value == null) {
            return "";
        }
        return value.replace("\\", "\\\\").replace("\t", "\\t")
            .replace("\r", "\\r").replace("\n", "\\n");
    }

    private String safe(String value) {
        return value.replaceAll("[^A-Za-z0-9_.-]", "_");
    }

    private String relative(File root, File child) {
        return root.toPath().relativize(child.toPath()).toString()
            .replace(File.separatorChar, '/');
    }

    private void mkdirs(File directory) {
        if (!directory.exists() && !directory.mkdirs()) {
            throw new IllegalStateException("cannot create " + directory);
        }
    }

    private PrintWriter writer(File directory, String name) throws Exception {
        return writer(new File(directory, name));
    }

    private PrintWriter writer(File file) throws Exception {
        return new PrintWriter(new BufferedWriter(new FileWriter(file)));
    }
}
