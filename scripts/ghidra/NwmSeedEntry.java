// Seed the raw Nintendo NWM .code segment before auto-analysis.
// @category Nintendo3DS

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class NwmSeedEntry extends GhidraScript {
    @Override
    protected void run() throws Exception {
        Address entry = toAddr(0x00100000L);
        currentProgram.getSymbolTable().addExternalEntryPoint(entry);
        disassemble(entry);
        Function function = getFunctionAt(entry);
        if (function == null) {
            createFunction(entry, "nwm_entry");
        } else {
            function.setName("nwm_entry", ghidra.program.model.symbol.SourceType.USER_DEFINED);
        }
        println("NWM seed: ARM entry at " + entry);
    }
}
