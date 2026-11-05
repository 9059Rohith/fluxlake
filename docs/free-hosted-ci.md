# Free hosted release verification — 5 November 2026

The four projects now run real tests inside their Vercel Linux container builds.
A final runtime image cannot be assembled without copying a receipt produced by
the successful verification stage. This is a working free hosted build gate,
separate from GitHub Actions, whose jobs remain blocked by the account lock.

## Executed scope

| Project | Hosted default tests passed | Explicit skips | Other hosted checks |
| --- | ---: | ---: | --- |
| Settlement Recon | 222 | 6 | Ruff lint/format; Bandit medium/high severity |
| FluxLake | 206 | 34 | Ruff source/gate lint |
| DataGuard | 217 | 1 | Ruff lint/format; Bandit medium/high severity |
| PipeFoundry | 126 | 23 | Ruff lint/format; Bandit source scan |

All four hosted builders used Python 3.15.1. The aggregate is **771 passed,
64 skipped**, with zero test failures or errors. This is the default build
profile, not a claim that optional integration tests ran inside the builder.
PostgreSQL, S3, Spark and container opt-ins have explicit skip reasons; earlier
executed integration evidence keeps its own environment and date.

The build gates reject failing commands, missing/empty test reports, failed or
errored test cases, and suites containing only skipped cases. Meaningful negative
regressions established those failure paths. Test tools and test fixtures remain
outside the final runtime. Build contexts exclude environment files, credentials,
Git metadata, Terraform state and local databases. Network-disabled verification
is used by Settlement Recon, FluxLake and DataGuard; PipeFoundry executes its
default isolated profile without configured integration credentials.

The receipts fingerprint the actual test/build inputs and record real JUnit
counts. Settlement Recon fingerprints its hosted build inputs, including generated
packaging metadata; its hash is not a portable Windows/Linux source identity.
The other three projects retain their own explicitly scoped fingerprints.
An independent read-only code review found no blocking gate defects.

## Security finding fixed during verification

The first FluxLake build-tool audit identified pytest 8.4.2 as affected by
[CVE-2025-71176](https://github.com/advisories/GHSA-6w46-j5rx-g56g).
Its development/build pin was upgraded to pytest 9.2.0, followed by the full gate
and a fresh audit. Runtime dependencies were unchanged, and pytest is excluded
from the runtime image. The original finding is retained rather than discarded.
Pinned build-tool dependency audits for all four projects found no known
vulnerabilities after this correction. An advisory scan is not a penetration
test or proof that every dependency is safe.

## Deployment and public retest evidence

See this repository's [release record](../evidence/free-hosted-ci/release.json),
[actual hosted receipt](../evidence/free-hosted-ci/receipt.json), and
[hosted build log](../evidence/free-hosted-ci/build.log). The release record
identifies the deployed source commit, immutable deployment and public URL.
Documentation/evidence commits after the release do not change runtime behavior.

Production builds were staged without assigning public domains, checked against
real database/source workflows, then promoted as the same tested builds. Public
verification covers database readiness, retained-source reads, FluxLake replay,
PipeFoundry typed manifest review, and rejection of unauthenticated operator
mutations. Separate bounded AI requests exercise actual provider calls and source
tools without an operator token. [Public API checks](../evidence/free-hosted-ci/public-api.json)
and [AI checks](../evidence/free-hosted-ci/public-ai.json) retain outcomes and
response fingerprints. Settlement Recon and FluxLake initially returned AI 503s;
after cooldown, their next bounded requests passed. All observations are retained.
These checks establish observed behavior, not uninterrupted provider availability.

Browser automation was unavailable in this task, so no new mobile/desktop browser
pass is claimed. Earlier dated browser evidence remains separate. This release
changes build verification and one reviewed static-HTML Bandit suppression, not
the visual design or public data model. Public data remains real retained source
evidence with observation times; it is not relabeled as a complete live stream.

## GitHub Actions: exact external blockers

The GitHub check annotation on all four repositories states:

> The job was not started because your account is locked due to a billing issue.

The [captured annotations](../evidence/free-hosted-ci/github-blocker.json) preserve
that evidence. A fresh [run/jobs/annotation capture for the deployed source
commit](../evidence/free-hosted-ci/github-latest-run.json) confirms the same lock
in each repository. These are jobs that never started, not test failures. Standard
public-repository runners are generally free under
[GitHub's billing rules](https://docs.github.com/en/billing/concepts/product-billing/github-actions),
but that does not remove this account-specific lock. No paid runner, plan upgrade,
payment change, or new self-hosted runner was configured.

The existing authorization also rejects workflow-file writes: the Git OAuth
connection lacks workflow scope and the connected GitHub integration returned
403, `Resource not accessible by integration`. Prepared immutable-action patches
remain at `docs/workflow-hardening.patch`; active workflow files were not silently
changed. The account lock and workflow-write authorization must be resolved at
the account/connection level before an actual passing GitHub Actions run can be
established. The Vercel gate is not presented as a GitHub Actions pass.

## AWS: free-only boundary

No AWS credentials, profile or configured region were available. No Terraform
apply was performed and no AWS resources were created. The ECS/RDS/ALB/EKS/DMS
profiles are not assumed to be free. Actual AWS deployment therefore remains
unverified. A verified AWS Free account plan and authorized credentials would be
required before evaluating an eligible deployment under the user's free-only
constraint. [AWS documents](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html)
that its Free account plan ends after six months or depleted credits; a Paid
account plan can incur charges beyond applicable credits. No paid fallback was
used. The existing Vercel team was verified as active Hobby; deployments reused
the existing Vercel/Neon setup without adding a paid resource.

## Reproduce

Use the project's documented local test command for its pinned environment, or
build its Dockerfile. The final image depends on the verification stage, so a
failing check stops release construction. Production publication uses a staged
`vercel deploy --prod --skip-domain`, explicit smoke checks, then `vercel promote`
of that exact deployment. Secrets remain in the existing hosting configuration;
they are neither downloaded nor committed as evidence.
