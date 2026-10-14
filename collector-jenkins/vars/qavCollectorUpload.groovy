// Deprecated: the step's name before the QEOS rename. Use qeosCollectorUpload.
//
// A Jenkinsfile written before the rename passes ref: 'collector-v0.3.0' (or older) and may run
// `.qav-venv/bin/python -m qav_collector ...` afterwards. For such a ref, or a `source` naming
// qav-collector, this step keeps the old behaviour exactly: it installs the package under its old
// name, qav-collector, into .qav-venv. Any other ref (collector-v0.4.0 and later, a branch, a SHA,
// or no ref) delegates to qeosCollectorUpload with the same parameters.
def call(Map config = [:]) {
    echo 'qavCollectorUpload is deprecated; use qeosCollectorUpload'
    if (!usesLegacyPackage(config)) {
        return qeosCollectorUpload(config)
    }
    String patterns = config.patterns ?: 'reports/**/*.xml'
    String ref = config.ref
    String source = config.source ?:
        "qav-collector @ git+https://github.com/atriis/Atriis.QEOS@${ref}#subdirectory=collector"
    String args = [
        config.environment ? "--environment '${config.environment}'" : '',
        config.caFile ? "--ca-file '${config.caFile}'" : '',
        config.failOnError ? '--fail-on-error' : '',
        config.extraArgs ?: '',
    ].findAll().join(' ')
    sh """
        python3 -m venv --clear .qav-venv
        .qav-venv/bin/python -m pip install --quiet '${source}'
        .qav-venv/bin/python -m qav_collector upload ${patterns} ${args}
    """
}

// True for a collector-vX.Y.Z ref older than 0.4.0 (the first release named qeos-collector),
// or a source that names the old package. NonCPS: a regex Matcher is not serializable.
@NonCPS
private boolean usesLegacyPackage(Map config) {
    if (config.source) {
        return config.source.toString().trim().startsWith('qav-collector')
    }
    def match = (config.ref ?: '').toString() =~ /^collector-v(\d+)\.(\d+)\.(\d+)$/
    if (!match.matches()) {
        return false
    }
    int major = match.group(1) as int
    int minor = match.group(2) as int
    return major == 0 && minor < 4
}
