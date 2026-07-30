export {};

declare global {
  type DesktopSetupPhase =
    | "fresh"
    | "profile_complete"
    | "vault_prepared"
    | "vault_committed"
    | "models_complete"
    | "memory_complete"
    | "security_complete"
    | "complete"
    | "recovery";

  interface DesktopSetupState {
    schema_version: 2;
    revision: number;
    phase: DesktopSetupPhase;
    editable_step: number;
    completed_capabilities: string[];
    next_required_action: string;
    recovery_reason?: "missing_vault_data" | "setup_state_invalid";
    profile: { display_name: string; avatar_path?: string };
    vault: { id: string; name: string; path: string };
    chat_setup: { status: string; model_id: string };
    model_storage: { download_root: string };
    memory_setup: { status: string; model_id: string };
    security_setup: { status: string };
    model_discovery: { status: string; operation_id: string; scan_all_drives: boolean };
    recoverable_error: {
      code: string;
      message: string;
      action: string;
      diagnostic_id: string;
    } | null;
    tour: { status: "pending" | "completed" | "skipped"; step: number; version: 1 };
    updated_at: string;
  }

  type DesktopSetupStatePatch = Partial<
    Omit<
      DesktopSetupState,
      "profile" | "vault" | "chat_setup" | "model_storage" | "memory_setup" |
      "security_setup" | "model_discovery" | "tour"
    >
  > & {
    profile?: Partial<DesktopSetupState["profile"]>;
    vault?: Partial<DesktopSetupState["vault"]>;
    chat_setup?: Partial<DesktopSetupState["chat_setup"]>;
    model_storage?: Partial<DesktopSetupState["model_storage"]>;
    memory_setup?: Partial<DesktopSetupState["memory_setup"]>;
    security_setup?: Partial<DesktopSetupState["security_setup"]>;
    model_discovery?: Partial<DesktopSetupState["model_discovery"]>;
    tour?: Partial<DesktopSetupState["tour"]>;
  };

  interface DesktopWindowState {
    maximized: boolean;
    fullScreen: boolean;
  }

  interface DesktopMcpLauncher {
    version: 1;
    app_version: string;
    command: string;
    args: string[];
    cwd: string;
    env: Record<string, string>;
    capability_profile: "read_only" | "read_write";
    packaged: boolean;
  }

  interface DesktopMcpFeatureFlags {
    chatgpt_mcp_setup: boolean;
    secure_mcp_tunnel: boolean;
    chatgpt_mcp_write_tools: boolean;
    mcp_streaming: boolean;
    mcp_remote_http: boolean;
  }

  interface DesktopTunnelStatus {
    state: "disconnected" | "connecting" | "connected" | "attention_required";
    tunnel_id: string;
    bridge_client_id: string;
    capability_profile: "read_only" | "read_write";
    ready: boolean;
    detail: string;
    health_url: string;
    last_connected_at: string | null;
    last_error_at: string | null;
  }

  interface Window {
    cmlDesktop?: {
      platform: NodeJS.Platform;
      windowControls: {
        getState: () => Promise<DesktopWindowState>;
        minimize: () => Promise<boolean>;
        toggleMaximize: () => Promise<DesktopWindowState>;
        close: () => Promise<boolean>;
        onStateChanged: (listener: (state: DesktopWindowState) => void) => () => void;
      };
      openPath: (targetPath: string) => Promise<boolean>;
      openExternal: (url: string) => Promise<boolean>;
      selectSourceFiles: () => Promise<string[]>;
      selectSourceFolders: () => Promise<string[]>;
      selectEmbeddingFolder: () => Promise<string | null>;
      selectModelFolder: () => Promise<string | null>;
      readLocalImage: (targetPath: string) => Promise<string | null>;
      deleteLocalMedia: (mediaId: string) => Promise<boolean>;
      selectModelCheckpoint: () => Promise<string | null>;
      selectVaultFolder: () => Promise<string | null>;
      prepareActiveVaultFolder: (targetPath: string) => Promise<string | null>;
      setActiveVaultFolder: (targetPath: string) => Promise<string | null>;
      moveActiveVaultFolder: (targetPath: string) => Promise<{
        backend_url: string | null;
        path: string;
        old_copy_removed: boolean;
      } | null>;
      clearActiveVaultFolder: () => Promise<string | null>;
      selectCoverImage: () => Promise<string | null>;
      getBackendUrl: () => Promise<string | null>;
      getBackendToken: () => Promise<string | null>;
      getMcpFeatureFlags: () => Promise<DesktopMcpFeatureFlags>;
      getMcpLauncher: (
        capabilityProfile: "read_only" | "read_write",
      ) => Promise<DesktopMcpLauncher>;
      getOdinLauncherStatus: () => Promise<{
        version: number;
        launcher_path: string;
        installed: boolean;
        needs_repair: boolean;
        on_current_path: boolean;
        expected_checksum: string;
        install_method?: "vault" | "uv";
        path_error?: string | null;
      }>;
      installOdinLauncher: () => Promise<{
        version: number;
        launcher_path: string;
        installed: boolean;
        needs_repair: boolean;
        available_in_new_shell: boolean;
        path_registered?: boolean;
        path_error?: string | null;
        help_ok: boolean;
      }>;
      installOdinWithUv: () => Promise<{
        version: number;
        launcher_path: string;
        installed: boolean;
        needs_repair: boolean;
        install_method: "uv";
        available_in_new_shell?: boolean;
        path_registered?: boolean;
        path_error?: string | null;
        help_ok: boolean;
      }>;
      startOdinPairing: () => Promise<{ started: boolean }>;
      getTunnelStatus: () => Promise<DesktopTunnelStatus | null>;
      connectTunnel: (configuration: {
        tunnelId: string;
        runtimeApiKey: string;
        bridgeToken: string;
        bridgeClientId?: string;
        capabilityProfile: "read_only" | "read_write";
      }) => Promise<DesktopTunnelStatus>;
      reconnectTunnel: (bridgeToken?: string) => Promise<DesktopTunnelStatus>;
      disconnectTunnel: (forget?: boolean) => Promise<DesktopTunnelStatus>;
      openTunnelUi: () => Promise<boolean>;
      onTunnelStatusChanged: (
        listener: (status: DesktopTunnelStatus) => void,
      ) => () => void;
      getSetupState: () => Promise<DesktopSetupState>;
      updateSetupState: (patch: DesktopSetupStatePatch) => Promise<DesktopSetupState>;
      resetAppSetup: () => Promise<DesktopSetupState>;
      finalizeActiveVaultDeletion: () => Promise<{ deleted: boolean; path: string }>;
      notifyRendererReady: (detail?: string) => Promise<boolean>;
      onBackendUrlChanged: (listener: (nextUrl: string | null) => void) => () => void;
      copyText: (value: string) => Promise<boolean>;
      openVaultAnyway: () => Promise<string | null>;
      listSupportedFiles: (targetPaths: string[]) => Promise<string[]>;
      scanSupportedFiles: (
        targetPaths: string[],
        limit?: number,
      ) => Promise<{ files: string[]; truncated: boolean; limit: number }>;
      getDroppedFilePaths: () => string[];
      showItemInFolder: (targetPath: string) => Promise<boolean>;
    };
  }
}
