# Third-Party Notices

This repository redistributes no third-party source code.

The skills' Python scripts declare their dependencies inline (PEP 723); `uv`
downloads those packages at run time from their own distributors, under their
own licenses. The Nix flake pins its inputs (`nixpkgs`, `agent-skills-nix`) in
`flake.lock` and fetches them the same way.
