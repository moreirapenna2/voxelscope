package dev.voxelscope;

import com.mojang.logging.LogUtils;
import net.neoforged.fml.common.Mod;
import net.neoforged.fml.loading.FMLPaths;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.server.ServerStartedEvent;
import net.neoforged.neoforge.event.server.ServerStoppingEvent;

@Mod(VoxelScope.MOD_ID)
public final class VoxelScope {
    public static final String MOD_ID = "voxelscope";
    private BridgeHttp bridge;

    public VoxelScope() {
        NeoForge.EVENT_BUS.addListener(this::started);
        NeoForge.EVENT_BUS.addListener(this::stopping);
    }

    private void started(ServerStartedEvent event) {
        try {
            bridge = new BridgeHttp(FMLPaths.GAMEDIR.get().resolve("voxelscope"),
                    new GameQueries(event.getServer()));
            bridge.start();
            LogUtils.getLogger().info("VoxelScope read-only API started on 127.0.0.1:{}", bridge.port());
        } catch (Exception error) {
            // Monitoring failure must not prevent the world from starting.
            LogUtils.getLogger().error("VoxelScope could not start; gameplay can continue", error);
        }
    }

    private void stopping(ServerStoppingEvent event) {
        if (bridge != null) {
            bridge.close();
            bridge = null;
        }
    }
}
