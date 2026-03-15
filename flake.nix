{
  description = "Sync Dropbox .fit files to Garmin Connect";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      pkgsFor = system: nixpkgs.legacyPackages.${system};
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = pkgsFor system;
          python = pkgs.python3;
        in
        {
          default = python.pkgs.buildPythonApplication {
            pname = "dropbox2garmin";
            version = "0.1.0";
            src = ./.;
            format = "pyproject";

            nativeBuildInputs = [ python.pkgs.setuptools ];

            propagatedBuildInputs = [
              python.pkgs.garminconnect
              python.pkgs.watchdog
            ];

            meta.mainProgram = "dropbox2garmin";
          };
        });

      homeManagerModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.services.dropbox2garmin;
          pkg = self.packages.${pkgs.system}.default;
        in
        {
          options.services.dropbox2garmin = {
            enable = lib.mkEnableOption "dropbox2garmin sync service";

            environmentFile = lib.mkOption {
              type = lib.types.path;
              description = "Path to .env file with Garmin credentials";
            };

            environment = lib.mkOption {
              type = lib.types.attrsOf lib.types.str;
              default = {};
              description = "Extra environment variables for the dropbox2garmin service";
            };
          };

          config = lib.mkIf cfg.enable {
            systemd.user.services.dropbox2garmin = {
              Unit = {
                Description = "dropbox2garmin";
                After = [ "network-online.target" ];
              };
              Service = {
                ExecStart = "${pkg}/bin/dropbox2garmin";
                Restart = "on-failure";
                RestartSec = 30;
                EnvironmentFile = cfg.environmentFile;
                Environment = lib.mapAttrsToList (k: v: "${k}=${v}") cfg.environment;
              };
              Install = {
                WantedBy = [ "default.target" ];
              };
            };
          };
        };

      devShells = forAllSystems (system:
        let
          pkgs = pkgsFor system;
          python = pkgs.python3;
        in
        {
          default = pkgs.mkShell {
            packages = [
              (python.withPackages (ps: [
                ps.garminconnect
                ps.watchdog
              ]))
            ];
          };
        });
    };
}
