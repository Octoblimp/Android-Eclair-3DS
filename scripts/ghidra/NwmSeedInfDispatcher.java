// Recover the large Thumb dispatcher reached through an indirect service callback.
// @category Nintendo3DS

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import java.math.BigInteger;

public class NwmSeedInfDispatcher extends GhidraScript {
    @Override
    protected void run() throws Exception {
        Address regionStart = toAddr(0x00104994L);
        Address regionEnd = toAddr(0x00106fa7L);
        for (Function function : currentProgram.getFunctionManager()
                .getFunctions(regionStart, true)) {
            if (function.getEntryPoint().compareTo(regionEnd) > 0) {
                break;
            }
            currentProgram.getFunctionManager().removeFunction(function.getEntryPoint());
        }
        clearListing(regionStart, regionEnd);
        Register tmode = currentProgram.getProgramContext().getRegister("TMode");
        currentProgram.getProgramContext().setValue(
            tmode, regionStart, regionEnd, BigInteger.ONE);

        long[] starts = { 0x00104994L, 0x001049ccL };
        String[] names = { "nwm_service_session_init", "nwm_inf_ipc_dispatch" };
        for (int i = 0; i < starts.length; i++) {
            Address address = toAddr(starts[i]);
            disassemble(address);
            if (getFunctionAt(address) == null) {
                createFunction(address, names[i]);
            }
            println("NWM seed: " + names[i] + " at " + address);
        }
    }
}
