// Export a reproducible raw analysis corpus for the Nintendo NWM host binary.
// @category Nintendo3DS

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;

public class NwmExportCorpus extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1) {
            throw new IllegalArgumentException("usage: NwmExportCorpus.java OUTPUT_DIR");
        }
        File output = new File(args[0]);
        if (!output.exists() && !output.mkdirs()) {
            throw new IllegalStateException("cannot create " + output);
        }

        PrintWriter functions = writer(output, "functions.tsv");
        PrintWriter strings = writer(output, "strings.tsv");
        PrintWriter refs = writer(output, "string_refs.tsv");
        PrintWriter decompiled = writer(output, "decompiled.c");
        functions.println("address\tname\tlength\tcalling_convention");
        strings.println("address\tvalue");
        refs.println("string_address\tfrom_address\treference_type\tvalue");

        for (Data data : currentProgram.getListing().getDefinedData(true)) {
            Object value = data.getValue();
            if (!(value instanceof String)) {
                continue;
            }
            String clean = ((String) value).replace("\\", "\\\\")
                .replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n");
            strings.println(data.getAddress() + "\t" + clean);
            for (Reference ref : currentProgram.getReferenceManager()
                    .getReferencesTo(data.getAddress())) {
                refs.println(data.getAddress() + "\t" + ref.getFromAddress() + "\t" +
                    ref.getReferenceType() + "\t" + clean);
            }
        }

        DecompInterface decompiler = new DecompInterface();
        decompiler.toggleCCode(true);
        decompiler.toggleSyntaxTree(true);
        decompiler.openProgram(currentProgram);
        FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
        int count = 0;
        while (iterator.hasNext() && !monitor.isCancelled()) {
            Function function = iterator.next();
            functions.println(function.getEntryPoint() + "\t" + function.getName(true) + "\t" +
                function.getBody().getNumAddresses() + "\t" + function.getCallingConventionName());
            decompiled.println("\n/* ===== " + function.getEntryPoint() + " " +
                function.getName(true) + " ===== */");
            DecompileResults result = decompiler.decompileFunction(function, 90, monitor);
            if (result.decompileCompleted() && result.getDecompiledFunction() != null) {
                decompiled.println(result.getDecompiledFunction().getC());
            } else {
                decompiled.println("/* DECOMPILE FAILED: " + result.getErrorMessage() + " */");
            }
            count++;
        }
        decompiler.dispose();
        functions.close();
        strings.close();
        refs.close();
        decompiled.close();
        println("NWM corpus: exported " + count + " functions to " + output);
    }

    private PrintWriter writer(File directory, String name) throws Exception {
        return new PrintWriter(new BufferedWriter(new FileWriter(new File(directory, name))));
    }
}
