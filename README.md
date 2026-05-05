[![Syntax Status](https://github.com/openemr/openemr/actions/workflows/syntax.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/syntax.yml)
[![Styling Status](https://github.com/openemr/openemr/actions/workflows/styling.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/styling.yml)
[![Testing Status](https://github.com/openemr/openemr/actions/workflows/test.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/test.yml)
[![JS Unit Testing Status](https://github.com/openemr/openemr/actions/workflows/js-test.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/js-test.yml)
[![PHPStan](https://github.com/openemr/openemr/actions/workflows/phpstan.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/phpstan.yml)
[![Rector](https://github.com/openemr/openemr/actions/workflows/rector.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/rector.yml)
[![ShellCheck](https://github.com/openemr/openemr/actions/workflows/shellcheck.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/shellcheck.yml)
[![Docker Compose Linting](https://github.com/openemr/openemr/actions/workflows/docker-compose-lint.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/docker-compose-lint.yml)
[![Dockerfile Linting](https://github.com/openemr/openemr/actions/workflows/hadolint.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/hadolint.yml)
[![Isolated Tests](https://github.com/openemr/openemr/actions/workflows/isolated-tests.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/isolated-tests.yml)
[![Inferno Certification Test](https://github.com/openemr/openemr/actions/workflows/inferno-test.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/inferno-test.yml)
[![Composer Checks](https://github.com/openemr/openemr/actions/workflows/composer.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/composer.yml)
[![Composer Require Checker](https://github.com/openemr/openemr/actions/workflows/composer-require-checker.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/composer-require-checker.yml)
[![API Docs Freshness Checks](https://github.com/openemr/openemr/actions/workflows/api-docs.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/api-docs.yml)
[![codecov](https://codecov.io/gh/openemr/openemr/graph/badge.svg?token=7Eu3U1Ozdq)](https://codecov.io/gh/openemr/openemr)

[![Backers on Open Collective](https://opencollective.com/openemr/backers/badge.svg)](#backers) [![Sponsors on Open Collective](https://opencollective.com/openemr/sponsors/badge.svg)](#sponsors)

# OpenEMR

## AgentForge Clinical Co-Pilot

This fork is being used for the AgentForge Clinical Co-Pilot project. The current submission checkpoint demonstrates the committed project direction: a hospitalist-focused, OpenEMR-integrated clinical assistant with bounded evidence retrieval, source-backed verification, and OpenEMR-owned authorization. The repository now includes the first agent execution slice, and the Railway environment runs OpenEMR, MariaDB, and the AgentForge sidecar in mock mode for deterministic demo behavior.

Current deployed checkpoint: https://openemr-production-5533.up.railway.app

Project documents:

Week 1 baseline:

- [Audit](docs/week-1/AUDIT.md): final security, performance, architecture, data quality, and compliance audit.
- [Users](docs/week-1/USERS.md): target hospitalist user, workflow, and use cases.
- [Architecture](docs/week-1/ARCHITECTURE.md): Clinical Co-Pilot architecture defense and AI integration plan.
- [PRD](docs/week-1/PRD.md): execution source of truth for the Week 1 Clinical Co-Pilot build.
- [Submission checkpoint](docs/week-1/MVP_SUBMISSION.md): checkpoint checklist, demo outline, limitations, and next steps.
- [Cost analysis](docs/week-1/COST_ANALYSIS.md): AI cost and scale analysis.

Week 2 multimodal expansion:

- [W2_ARCHITECTURE.md](W2_ARCHITECTURE.md): canonical Week 2 architecture defense for the multimodal evidence agent.
- [Week 2 PRD notes](docs/week-2/PRD_NOTES.md): extracted requirement summary and guardrails.
- [Week 2 eval plan](docs/week-2/EVAL_PLAN.md): 50-case boolean eval gate strategy.
- [Week 2 cost and latency plan](docs/week-2/COST_LATENCY_PLAN.md): measurement and bottleneck plan.

Eval references:

- [agentforge/evals/EVALS.md](agentforge/evals/EVALS.md): eval philosophy, examples, and evals-vs-unit-tests explanation.
- [agentforge/evals/RESULTS.md](agentforge/evals/RESULTS.md): current eval runner instructions and latest smoke results.

The project architecture keeps OpenEMR as the clinical trust boundary. OpenEMR owns authentication, patient context, authorization, evidence retrieval, and audit logging. The in-repo sidecar architecture handles AI orchestration and verification in a separate runtime boundary, and the sidecar receives only bounded evidence bundles from OpenEMR rather than direct database credentials or independent chart-retrieval authority. Week 2 keeps this boundary while planning document ingestion, source-cited extraction, guideline retrieval, an inspectable supervisor graph, and eval-driven CI.

The first execution slice now includes an OpenEMR custom module shell at `interface/modules/custom_modules/agentforge/`, shared contracts under `agentforge/contracts/`, a FastAPI sidecar under `agentforge/sidecar/`, and eval smoke tests under `agentforge/evals/`. The public Railway OpenEMR deployment remains demo-data-only, with production HIPAA readiness reserved for the compliance gate described in `AUDIT.md`. Real OpenAI mode is enabled only with a server-side `OPENAI_API_KEY` and reviewed configuration.

This checkpoint is demo-data-only. Use synthetic or demo patient data with the Railway deployment.

### Local OpenEMR With Sample Patients

The local audit and architecture work should be done against a runnable OpenEMR instance with realistic synthetic patient data. This project uses OpenEMR's standard Docker development environment plus imported Synthea C-CDA patients, which avoids hand-written SQL and keeps the sample data clearly synthetic.

1. Start the OpenEMR development environment:

   ```shell
   cd docker/development-easy
   docker compose up
   ```

2. Open the local app at `http://localhost:8300/` or `https://localhost:9300/`.

3. Log in with the standard local development credentials:

   ```text
   username: admin
   password: pass
   ```

4. Download synthetic C-CDA sample patients from [Synthea](https://synthetichealth.github.io/synthea/). Use the C-CDA download, unzip it, and keep a few patient `.xml` files for the demo dataset.

5. In OpenEMR, enable the C-CDA workflow if it is not already visible:

   ```text
   Admin -> Globals -> Connectors -> Enable C-CDA Service
   ```

   Choose `Care Coordination Only` or `Both`, then save. If needed, go to `Modules -> Manage Modules` and enable the Carecoordination module and any required dependencies.

6. Import the synthetic patients:

   ```text
   Modules -> Carecoordination -> Import -> CCDA or QRDA Cat I
   ```

   Upload a Synthea `.xml` file. When the imported row appears, choose `Add as new patient`.

7. Verify the data is usable for analysis:

   ```text
   Patient/Client -> New/Search
   ```

   Search for the imported patient name and confirm that demographics, medications, problems, allergies, vitals, and notes imported well enough to support audit and architecture testing.

Use synthetic patient data in local development. The sample-patient workflow is intentionally synthetic and is meant to support system analysis, demo preparation, and later evidence-bundle testing.

The Railway deployment uses a small `Dockerfile.railway` based on the official OpenEMR image so the submitted checkpoint is built from this fork while preserving the known OpenEMR runtime. Railway is configured with separate OpenEMR, MariaDB, and `agentforge-sidecar` services; OpenEMR reaches the sidecar over Railway private networking.

### AgentForge Runtime Configuration

The OpenEMR module calls the sidecar when these server-side variables are configured. `AGENTFORGE_SIGNING_SECRET` is required; missing secrets fail closed instead of using a development default.

```text
AGENTFORGE_SIDECAR_URL=http://agentforge-sidecar:8000
AGENTFORGE_SIGNING_SECRET=<shared-secret>
AGENTFORGE_MODE=mock
OPENAI_API_KEY=<real-mode-only>
AGENTFORGE_OPENAI_MODEL=gpt-4.1-mini
```

Use `AGENTFORGE_MODE=mock` for deterministic demos, `real` for OpenAI-backed responses, and `off` for rollback. Browser code never receives the sidecar signing secret or OpenAI API key.

[OpenEMR](https://open-emr.org) is a Free and Open Source electronic health records and medical practice management application. It features fully integrated electronic health records, practice management, scheduling, electronic billing, internationalization, free support, a vibrant community, and a whole lot more. It runs on Windows, Linux, Mac OS X, and many other platforms.

### Contributing

OpenEMR is a leader in healthcare open source software and comprises a large and diverse community of software developers, medical providers and educators with a very healthy mix of both volunteers and professionals. [Join us and learn how to start contributing today!](https://open-emr.org/wiki/index.php/FAQ#How_do_I_begin_to_volunteer_for_the_OpenEMR_project.3F)

> Already comfortable with git? Check out [CONTRIBUTING.md](CONTRIBUTING.md) for quick setup instructions and requirements for contributing to OpenEMR by resolving a bug or adding an awesome feature 😊.

### Support

Community and Professional support can be found [here](https://open-emr.org/wiki/index.php/OpenEMR_Support_Guide).

Extensive documentation and forums can be found on the [OpenEMR website](https://open-emr.org) that can help you to become more familiar about the project 📖.

### Reporting Issues and Bugs

Report these on the [Issue Tracker](https://github.com/openemr/openemr/issues). If you are unsure if it is an issue/bug, then always feel free to use the [Forum](https://community.open-emr.org/) and [Chat](https://www.open-emr.org/chat/) to discuss about the issue 🪲.

### Reporting Security Vulnerabilities

Check out [SECURITY.md](.github/SECURITY.md)

### API

Check out [API_README.md](API_README.md)

### Docker

Check out [DOCKER_README.md](DOCKER_README.md)

### FHIR

Check out [FHIR_README.md](FHIR_README.md)

### For Developers

If using OpenEMR directly from the code repository, then the following commands will build OpenEMR (Node.js version 24.* is required) :

```shell
composer install --no-dev
npm install
npm run build
composer dump-autoload -o
```

### Contributors

This project exists thanks to all the people who have contributed. [[Contribute]](CONTRIBUTING.md).
<a href="https://github.com/openemr/openemr/graphs/contributors"><img src="https://opencollective.com/openemr/contributors.svg?width=890" /></a>


### Sponsors

Thanks to our [ONC Certification Major Sponsors](https://www.open-emr.org/wiki/index.php/OpenEMR_Certification_Stage_III_Meaningful_Use#Major_sponsors)!


### License

[GNU GPL](LICENSE)
