# Risk Register

Likelihood/Impact: L/M/H. Status: Open, Mitigating, Closed, Accepted.

| ID | Risk | L | I | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| R-MKT-01 | No validated demand; feasibility (past shock absorber/bipod work) ≠ market pull | H | H | Pilot interviews before M2 scope lock (COM-001); measure time saved | Founder | Open |
| R-MKT-02 | Incumbent CAD vendors ship similar AI features, compressing wedge | M | H | Differentiate on manufacturability, verified checks, workflow integration, data | Founder | Open |
| R-TEC-01 | LLM produces spec that passes geometry checks but misses design intent | H | H | Echo-back of interpreted requirements, assumption list, human approval gate, intent tests | Eng | Open |
| R-TEC-02 | OCCT boolean/fillet failures on edge cases | M | M | Validity checks, fallback ordering, fuzz tests over parameter ranges | Eng | Open |
| R-TEC-03 | Auto-dimensioned drawings cluttered or wrong; low trust | H | H | Dimensions from spec not geometry; "inferred" labels; engineer review gate | Eng | Open |
| R-TEC-04 | Topological naming breaks edits/revisions | M | H | Feature IDs + semantic selectors in DSL; avoid raw face indices | Eng | Open |
| R-TEC-05 | Vision critique hallucinates mismatches or misses errors | H | M | Vision is advisory; deterministic checks gate acceptance | Eng | Open |
| R-TEC-06 | build123d small maintainer base; API churn | M | M | Pin versions; wrap behind compiler; CadQuery fallback | Eng | Open |
| R-TEC-07 | Windows-only dev environment hides Linux deployment issues | M | M | Add Linux CI early (GitHub Actions or WSL) | Eng | Open |
| R-SEC-01 | Untrusted code execution (LLM-authored scripts, Blender) | H | H | DSL-only in M1; container sandbox before code fallback (SEC-004) | Eng | Mitigating (by design) |
| R-SEC-02 | Malicious uploads (STEP/PDF/images: parser bugs, zip bombs, path traversal) | M | H | Size/type limits, isolated parsing worker, path sanitization | Eng | Open |
| R-SEC-03 | Prompt injection via uploaded drawings/text | M | M | Treat file text as data; tool-call allowlists; no secrets in worker | Eng | Open |
| R-SEC-04 | Customer confidential/ITAR/EAR-controlled CAD sent to third-party AI | M | H | Data classification at upload, no-AI mode, contractual DPAs, export-control screening | Founder/Counsel | Open |
| R-LIC-01 | Copyleft obligations (OCCT LGPL, FreeCAD LGPL, Blender GPL, SolveSpace GPL-3) | M | H | Transitive audit (LEG-002); keep GPL tools out-of-process; counsel | Counsel | Open |
| R-LIC-02 | cadquery-ocp wheel bundles OCCT DLLs but ships no OCCT license text in dist-info (observed 2026-11-16) | M | M | Include OCCT LGPL notice + source offer in any distribution; counsel review | Counsel | Open |
| R-LIC-03 | CAD vendor API/EULA restricts automation or SaaS use (SOLIDWORKS, Creo) | M | M | Review partner/API terms before any bridge work | Counsel | Open |
| R-LIC-04 | AI provider terms (output ownership, data retention, training) unfavourable for customers | L | M | Review Anthropic commercial terms (LEG-005); provider abstraction | Counsel | Open |
| R-IP-01 | Past client/employer material leaks into fixtures or prompts | L | H | Original fixtures only; provenance field on every fixture | Founder | Open |
| R-ENG-01 | Users treat AI engineering advice as validated | M | H | Advice levels (recommended/preliminary/verified/validated), sign-off gate, disclaimers | Eng | Open |
| R-OPS-01 | Unbounded agent loops → runaway cost | M | M | Iteration/time/cost caps per job; metering | Eng | Open |
| R-OPS-02 | No Docker/WSL distro on dev box blocks isolation work | H | M | Approval to install Docker Desktop or WSL2 distro | Founder | Open |
| R-OPS-03 | Directory not under version control → evidence links impossible | H | L | `git init` after approval | Founder | Open |
