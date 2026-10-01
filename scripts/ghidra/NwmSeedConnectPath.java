// Recover Thumb functions on NWM's encrypted-AP-to-WMI connect path.
// @category Nintendo3DS

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import java.math.BigInteger;

public class NwmSeedConnectPath extends GhidraScript {
    @Override
    protected void run() throws Exception {
        long[] starts = {
            0x00118818L, 0x0011a20eL, 0x0011a2b8L, 0x0011a330L,
            0x0011a390L, 0x0011a51cL, 0x0011aa2cL, 0x0011aac0L,
            0x0011ab04L, 0x0012a1e8L, 0x0012a7a0L, 0x0012b0f0L,
            0x0013154cL, 0x00131d40L, 0x00132568L, 0x00132954L, 0x001329acL,
            0x00132becL, 0x00133030L, 0x00135d20L, 0x00136a14L
        };
        String[] names = {
            "nwm_wmi_connect_cmd", "nwm_connect_setup_11a20e",
            "nwm_connect_setup_11a2b8", "nwm_connect_setup_11a330",
            "nwm_connect_setup_11a390", "nwm_connect_setup_11a51c",
            "nwm_connect_setup_11aa2c", "nwm_connect_setup_11aac0",
            "nwm_connect_setup_11ab04", "nwm_connect_setup_12a1e8",
            "nwm_connect_setup_12a7a0", "nwm_encrypted_ap_message",
            "nwm_wifi_state_init", "nwm_connect_profile", "nwm_connect_setup_132568",
            "nwm_connect_setup_132954", "nwm_connect_setup_1329ac",
            "nwm_connect_setup_132bec", "nwm_set_scan_params",
            "nwm_wmi_context_create", "nwm_wmi_set_keepalive_cmd"
        };
        Register tmode = currentProgram.getProgramContext().getRegister("TMode");
        for (int i = 0; i < starts.length; i++) {
            Address address = toAddr(starts[i]);
            Function function = getFunctionAt(address);
            if (function == null) {
                currentProgram.getProgramContext().setValue(
                    tmode, address, address.add(1), BigInteger.ONE);
                disassemble(address);
                function = createFunction(address, names[i]);
            }
            function.setName(names[i], SourceType.USER_DEFINED);
            println("NWM connect seed: " + names[i] + " at " + address);
        }
    }
}
