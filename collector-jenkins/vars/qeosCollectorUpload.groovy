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
// The agent needs Python 3.9+ and git on PATH. The collector is installed
// pinned to this library's `ref` (a collector-v* tag), so builds stay
// reproducible. `source` overrides the whole pip requirement (e.g. a local
// checkout or an internal mirror).
def call(Map config = [:]) {
    String patterns = config.patterns ?: 'reports/**/*.xml'
    String ref = config.ref ?: 'collector-v0.6.0'
    String source = config.source ?:
        "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@${ref}#subdirectory=collector"
    String args = [
        config.environment ? "--environment '${config.environment}'" : '',
        config.caFile ? "--ca-file '${config.caFile}'" : '',
        config.failOnError ? '--fail-on-error' : '',
        config.extraArgs ?: '',
    ].findAll().join(' ')
    // A venv in the workspace: modern Debian/Ubuntu agents refuse system pip
    // installs (PEP 668), and --user can collide between jobs on one agent
    sh """
        python3 -m venv --clear .qeos-venv
        .qeos-venv/bin/python -m pip install --quiet '${source}'
        .qeos-venv/bin/python -m qeos_collector upload ${patterns} ${args}
    """
}
