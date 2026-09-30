{ agentSkillsModule, agentLib }:

{ config, lib, pkgs, ... }:

let
  cfg = config.programs.agent-skills;
  sources = import ./sources.nix;
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

  config = {
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
  };
}
