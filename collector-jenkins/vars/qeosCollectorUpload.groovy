// Upload JUnit/TRX/NUnit/xUnit/TestNG/Cucumber reports to a QEOS platform.
//
// Usage (QEOS_URL and QEOS_API_KEY come from the caller, the key from a Jenkins credential):
//
//   withCredentials([string(credentialsId: 'qeos-api-key', variable: 'QEOS_API_KEY')]) {
//     withEnv(["QEOS_URL=https://qeos.example.com"]) {
//       qeosCollectorUpload(patterns: 'reports/**/*.xml', environment: 'staging')
//     }
//   }
//
// Suggested tests first (collector 0.7.0, Cucumber): the step runs the tests itself, so call it in
// the test stage, not in `post`. A failing test fails the build, as the test command would:
//
//   qeosCollectorUpload(impact: 'first', testCommand: 'npx cucumber-js --tags "not @wip"')
//   qeosCollectorUpload(impact: 'only', testCommand: 'mvn -q test')   // only the likely affected
//
// testCommand runs as `bash -c "$QEOS_TEST_COMMAND"`, as written (quotes included): the same trust
// as an `sh` step of the Jenkinsfile. It reaches the shell through the environment, never as part
// of this step's script.
//
// The agent needs Python 3.9+, git and bash on PATH. The collector is installed
// pinned to this library's `ref` (a collector-v* tag), so builds stay
// reproducible. `source` overrides the whole pip requirement (e.g. a local
// checkout or an internal mirror).
def call(Map config = [:]) {
    String patterns = config.patterns ?: 'reports/**/*.xml'
    String ref = config.ref ?: 'collector-v0.8.0'
    String impact = (config.impact ?: 'off').toString()
    if (!(impact in ['off', 'first', 'only'])) {
        error("qeosCollectorUpload: impact must be 'off', 'first' or 'only'")
    }
    if (impact != 'off' && !config.testCommand) {
        error("qeosCollectorUpload: impact '${impact}' needs testCommand, the Cucumber command to run")
    }
    String source = config.source ?:
        "qeos-collector @ git+https://github.com/atriis/Atriis.QEOS@${ref}#subdirectory=collector"
    String args = [
        config.environment ? "--environment '${config.environment}'" : '',
        config.caFile ? "--ca-file '${config.caFile}'" : '',
        config.failOnError ? '--fail-on-error' : '',
        config.extraArgs ?: '',
    ].findAll().join(' ')
    String command = impact == 'off'
        ? "upload ${patterns} ${args}"
        : "run-impact ${args} ${impact == 'only' ? '--suggested-only' : ''} -- bash -c \"\$QEOS_TEST_COMMAND\""
    // A venv in the workspace: modern Debian/Ubuntu agents refuse system pip
    // installs (PEP 668), and --user can collide between jobs on one agent
    withEnv(["QEOS_TEST_COMMAND=${config.testCommand ?: ''}"]) {
        sh """
            python3 -m venv --clear .qeos-venv
            .qeos-venv/bin/python -m pip install --quiet '${source}'
            .qeos-venv/bin/python -m qeos_collector ${command}
        """
    }
}
