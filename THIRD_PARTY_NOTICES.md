> Historical dependency inventory for v0.1.0-showcase. The current full application inventory is [here](docs/dependency-licenses-full.json), with [additional notices](docs/third-party-notices-full.md).

# Third-party notices

Dependencies retain their upstream licenses. This candidate does not relicense them or the original application code. Install environments, node_modules and built bundles are excluded from Git.

The reviewed installation is indexed in [dependency-licenses.json](docs/dependency-licenses-full.json). It includes version, declared license metadata and SHA-256 of available installed license files. npm optional platform packages can be listed in the lock without being installed on this machine. Actual Python license texts remain in their installed dist-info directories; installed npm license files remain with their packages.

If distributing a built image, bundle, or dependency source later, include the applicable upstream license and attribution files with that artifact. The current deliverable is repository source, with no dependency binaries archived into it. Container image versions and content digests are recorded separately in the local acceptance report; image use is not a new license grant.

## Python dependencies

| Name | Version | Declared license / available notice |
|---|---|---|
| alembic | 1.18.5 | MIT |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.16.0 | MIT |
| argon2-cffi | 25.1.0 | MIT |
| argon2-cffi-bindings | 26.1.0 | MIT |
| certifi | 2026.10.23 | MPL-2.0 |
| cffi | 2.1.1 | MIT-0 |
| click | 8.5.0 | BSD-3-Clause |
| fastapi | 0.139.2 | MIT |
| greenlet | 3.5.6 | MIT AND PSF-2.0 |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httptools | 0.9.0 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.1 | MIT |
| Mako | 1.4.3 | MIT |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| playwright | 1.58.0 | Apache-2.0 |
| pluggy | 1.7.0 | MIT |
| psycopg | 3.3.4 | LGPL-3.0-only |
| psycopg-binary | 3.3.4 | LGPL-3.0-only |
| pycparser | 3.12 | BSD-3-Clause |
| pydantic | 2.14.2 | MIT |
| pydantic-settings | 2.14.2 | MIT |
| pydantic_core | 2.50.2 | MIT |
| pyee | 13.0.1 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| pytest | 8.4.2 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| SQLAlchemy | 2.0.51 | MIT |
| starlette | 1.10.0 | BSD-3-Clause |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| uvicorn | 0.51.0 | BSD-3-Clause |
| uvloop | 0.23.0 | MIT License |
| watchfiles | 1.3.0 | MIT |
| websockets | 17.4 | BSD-3-Clause |

## npm metadata

0 locked package entries; exact versions, declared licenses and available installed file fingerprints are in the JSON index.
