{
  description = "OnPing agent skills, declaratively synced via agent-skills-nix";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    agent-skills-nix = {
      url = "github:Kyure-A/agent-skills-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, agent-skills-nix }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;

      agentLib = agent-skills-nix.lib.agent-skills;

      sources = import ./nix/sources.nix;
      # Each allowlist is present only in the flakes it governs: this repository
      # carries both, the public export carries public-allowlist.nix, and the
      # onping-skills export carries neither.
      publicAllowlist =
        if builtins.pathExists ./nix/public-allowlist.nix
        then import ./nix/public-allowlist.nix else null;
      onpingAllowlist =
        if builtins.pathExists ./nix/onping-skills-allowlist.nix
        then import ./nix/onping-skills-allowlist.nix else null;

      # Targets used by the standalone `nix run .#skills-install*` apps.
      # The Home Manager module sets these via the option system in nix/home.nix
      # (so upstream defaults like `dest` and `systems` deep-merge); these literal
      # attrsets are only consumed by mkSyncScript / mkLocalInstallScript, which
      # don't go through option merging.
      homeTargets = {
        claude = agentLib.defaultTargets.claude // { enable = true; structure = "copy-tree"; };
        agents = agentLib.defaultTargets.agents // { enable = true; structure = "copy-tree"; };
      };

      localTargets = {
        claude = agentLib.defaultLocalTargets.claude // { enable = true; structure = "copy-tree"; };
        agents = agentLib.defaultLocalTargets.agents // { enable = true; structure = "copy-tree"; };
      };

      catalog = agentLib.discoverCatalog sources;
      allowlist = agentLib.allowlistFor {
        inherit catalog sources;
        enableAll = true;
        enable = [];
      };
      selection = agentLib.selectSkills {
        inherit catalog allowlist sources;
        skills = {};
      };

      bundleFor = system:
        agentLib.mkBundle {
          pkgs = nixpkgs.legacyPackages.${system};
          inherit selection;
          name = "onping-skills";
        };

      # Content-exact copy-tree sync.
      #
      # The upstream copy-tree sync is `rsync -aL --delete` with no --checksum.
      # rsync's quick check skips a file whose size and mtime match, and every
      # Nix store file has mtime 1970-01-01, so an edit that keeps a file's size
      # never reaches the installed copy. Add -c to the copy-tree sync in
      # skills-install, skills-install-local, and the dev shell.
      #
      # NOT covered: homeManagerModules.default. It wraps the upstream Home
      # Manager module, which builds its own sync script; README.md and
      # SKILLS.md tell Home Manager users to run `nix run .#skills-install`.
      #
      # Fail closed: if upstream stops emitting the pattern (after
      # `nix flake update agent-skills-nix`), stop the build instead of
      # silently installing without content comparison.
      checksumSync = rec {
        from = "rsync -aL --delete";
        to = "rsync -aLc --delete";
        missing = "checksumSync: upstream copy-tree rsync pattern '${from}' not found"
          + " — agent-skills-nix changed; re-check flake.nix";
        # For script text (agentLib.mkSyncScript).
        text = s:
          if nixpkgs.lib.hasInfix from s
          then builtins.replaceStrings [ from ] [ to ] s
          else throw missing;
        # For a finished script derivation (agentLib.mkLocalInstallScript).
        drv = pkgs: script: name: pkgs.runCommand "${name}-checksum" { } ''
          mkdir -p "$out/bin"
          cp ${script}/bin/${name} "$out/bin/${name}"
          chmod u+w "$out/bin/${name}"
          if ! grep -qF -- '${from}' "$out/bin/${name}"; then
            echo ${nixpkgs.lib.escapeShellArg missing} >&2
            exit 1
          fi
          substituteInPlace "$out/bin/${name}" --replace-fail '${from}' '${to}'
        '';
      };

      # The two patched sync entry points, shared by apps, the dev shell, and
      # checks, so all three use the same derivations.
      syncScriptsFor = system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          bundle = bundleFor system;
        in
        {
          install = pkgs.writeShellApplication {
            name = "skills-install";
            runtimeInputs = [ pkgs.rsync pkgs.coreutils ];
            text = checksumSync.text (agentLib.mkSyncScript {
              inherit pkgs bundle;
              targets = homeTargets;
              system = pkgs.stdenv.hostPlatform.system;
              allowOverrides = true;
            });
          };
          # Also the dev-shell hook: agentLib.mkShellHook would run its own
          # unpatched copy of this script.
          installLocal = checksumSync.drv pkgs
            (agentLib.mkLocalInstallScript {
              inherit pkgs bundle;
              targets = localTargets;
            })
            "skills-install-local";
        };

      # Smoke-test sentinel, derived rather than hardcoded.
      #
      # The check must hold in two flakes built from this logic: this one, whose
      # catalog spans every provider, and the exported public flake, whose
      # catalog is restricted to nix/public-allowlist.nix. A literal sentinel
      # drawn from a non-exported provider (`grip`, in devtools/) fails in the
      # public flake with nothing actually wrong, and any literal goes stale the
      # next time the publishable roster changes.
      #
      # Resolve the first skill belonging to the first public source, or, in a
      # flake with no public allowlist (the onping-skills export, whose only
      # source is the one it publishes), to the first source. Fail loudly if
      # that yields nothing — a check that passes vacuously is worse than no
      # check, because everything downstream trusts it.
      sentinelSource =
        let s = if publicAllowlist == null
                then builtins.attrNames sources
                else publicAllowlist.publicSources;
        in if s == [] then throw "skill-sync-smoke: no source to derive a sentinel from"
           else builtins.head s;

      sentinelSkill =
        let
          fromSource = nixpkgs.lib.filterAttrs
            (_: skill: skill.source == sentinelSource) catalog;
          ids = builtins.attrNames fromSource;
        in
        if ids == [] then
          throw ("skill-sync-smoke: source '${sentinelSource}' contributed no skill "
            + "to the catalog, so no sentinel could be resolved")
        else builtins.head ids;
    in
    {
      packages = forAllSystems (system: {
        default = bundleFor system;
        agent-skills-bundle = bundleFor system;
      });

      apps = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          sync = syncScriptsFor system;

          listJson = pkgs.writeText "agent-skills-catalog.json"
            (builtins.toJSON (agentLib.catalogJson catalog));

          listScript = pkgs.writeShellApplication {
            name = "skills-list";
            runtimeInputs = [ pkgs.jq pkgs.coreutils ];
            text = ''
              ${pkgs.jq}/bin/jq . ${listJson}
            '';
          };
        in
        {
          skills-install = {
            type = "app";
            program = "${sync.install}/bin/skills-install";
          };
          skills-install-local = {
            type = "app";
            program = "${sync.installLocal}/bin/skills-install-local";
          };
          skills-list = {
            type = "app";
            program = "${listScript}/bin/skills-list";
          };
        });

      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          # What agentLib.mkShellHook produces, but with the patched script.
          default = pkgs.mkShellNoCC {
            shellHook = ''
              ${(syncScriptsFor system).installLocal}/bin/skills-install-local
            '';
          };
        });

      checks = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          bundle = bundleFor system;
        in
        {
          skill-sync-smoke = pkgs.runCommand "skill-sync-smoke" { } ''
            set -e
            if [ ! -e "${bundle}/${sentinelSkill}" ]; then
              echo "smoke-test FAIL: sentinel skill '${sentinelSkill}' (from source '${sentinelSource}') missing from bundle ${bundle}" >&2
              exit 1
            fi
            if [ ! -e "${bundle}/${sentinelSkill}/SKILL.md" ]; then
              echo "smoke-test FAIL: sentinel SKILL.md missing at ${bundle}/${sentinelSkill}/SKILL.md" >&2
              exit 1
            fi
            mkdir -p "$out"
            touch "$out/ok"
          '';

          # Every copy-tree rsync in the patched entry points compares content.
          skills-sync-checksum =
            let sync = syncScriptsFor system;
            in pkgs.runCommand "skills-sync-checksum" { } ''
              set -e
              for f in ${sync.install}/bin/skills-install ${sync.installLocal}/bin/skills-install-local; do
                if grep -n 'rsync -aL ' "$f"; then
                  echo "skills-sync-checksum FAIL: copy-tree rsync without -c in $f" >&2
                  exit 1
                fi
                if ! grep -q 'rsync -aLc --delete' "$f"; then
                  echo "skills-sync-checksum FAIL: no checksum copy-tree rsync in $f" >&2
                  exit 1
                fi
              done
              mkdir -p "$out"
              touch "$out/ok"
            '';
        } // pkgs.lib.optionalAttrs (onpingAllowlist != null) {
          # Evaluating the allowlist runs its fail-closed asserts: every OnPing
          # skill classified, no unknown or duplicate IDs, helper closure. The
          # derivation only exists if evaluation succeeded.
          onping-skills-allowlist = pkgs.writeText "onping-skills-allowlist.json"
            (builtins.toJSON onpingAllowlist);
        });

      homeManagerModules.default = import ./nix/home.nix {
        agentSkillsModule = agent-skills-nix.homeManagerModules.default;
        inherit agentLib;
      };

      lib = {
        inherit sources homeTargets localTargets catalog selection;
      };
    };
}
