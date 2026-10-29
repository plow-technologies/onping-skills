{ agentSkillsModule, agentLib, checksumSync, patchChecksum ? true }:

{ config, lib, pkgs, ... }:

let
  cfg = config.programs.agent-skills;
  sources = import ./sources.nix;

  # The upstream module's activation script, re-derived because the module
  # system cannot read the entry it is overriding. Mirrors
  # modules/home-manager/agent-skills.nix in agent-skills-nix at c6cb03f.
  # checks.skills-sync-checksum fails if this stops matching upstream in
  # anything but the checksumSync patch.
  system = pkgs.stdenv.hostPlatform.system;
  syncTargets = lib.filterAttrs (_: t: t.structure != "link")
    (agentLib.targetsFor { targets = cfg.targets; inherit system; });
  syncScript = agentLib.mkSyncScript {
    inherit pkgs system;
    bundle = cfg.bundlePath;
    targets = syncTargets;
    excludePatterns = cfg.excludePatterns;
  };
in
{
  imports = [ agentSkillsModule ];

  options.programs.agent-skills.codexLegacyHomeRoot = lib.mkOption {
    type = lib.types.bool;
    default = false;
    description = ''
      Also sync to ~/.codex/skills (legacy/compat target). Off by default.
      Enable only on machines where the installed Codex CLI version is verified
      to scan that path; otherwise prefer the agents target ($HOME/.agents/skills).
    '';
  };

  config = lib.mkMerge [
    {
      programs.agent-skills.enable = lib.mkDefault true;
      programs.agent-skills.sources = lib.mkDefault sources;
      programs.agent-skills.skills.enableAll = lib.mkDefault true;

      programs.agent-skills.targets.claude.enable = lib.mkDefault true;
      programs.agent-skills.targets.claude.structure = lib.mkDefault "copy-tree";
      programs.agent-skills.targets.agents.enable = lib.mkDefault true;
      programs.agent-skills.targets.agents.structure = lib.mkDefault "copy-tree";

      programs.agent-skills.targets.codex = lib.mkIf cfg.codexLegacyHomeRoot {
        enable = lib.mkDefault true;
        structure = lib.mkDefault "copy-tree";
      };
    }

    # Content-exact activation: the upstream entry, with every copy-tree rsync
    # patched to -c. See checksumSync in flake.nix. mkForce replaces the
    # upstream definition, and any consumer's, so the guarantee holds.
    (lib.mkIf (patchChecksum && cfg.enable && syncTargets != { }) {
      home.activation.agent-skills = lib.mkForce
        (lib.hm.dag.entryAfter [ "writeBoundary" ] (checksumSync.text syncScript));
    })
  ];
}
