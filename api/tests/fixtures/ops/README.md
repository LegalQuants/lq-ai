# Deployment-migration state fixtures

These are deliberately small **detector/reconciliation** fixtures. The
`xl.meta` placeholder is not a loadable MinIO object; it lets unit tests prove
that offline counting ignores system metadata. The real MinIO → RustFS byte
compatibility remains covered by the recorded ADR 0036 rehearsal and the
stack-smoke API byte round trip.
