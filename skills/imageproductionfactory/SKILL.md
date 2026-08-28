---
name: imageproductionfactory
description: Run intent-first, reference-faithful image production for an ImageGenSource target through purpose-based retrieval, item-specific creative planning, Grok Imagine and Codex gpt-image-2 queues, and semantic visual verification. Use for /imageproductionfactory or requests to produce, test, resume, or verify target image batches.
---

# Image Production Factory

Produce a requested set of images from an existing ImageGenSource target. The
host agent recognizes intent and authors the creative plan. The scripts enforce
contracts, compile provider prompts, run resumable queues, and verify evidence.

Read references/brief-contract.md before authoring a run. Use the examples in
templates only as schema examples; never treat their content as the current
user's intent.

## Non-negotiable model

The first stage is intelligent semantic processing by the host agent.

Do not infer intent from focus keywords, prompt templates, site cases,
filenames, visual medium, or a provider's system prompt. Preserve the current
user request verbatim and distinguish:

- what artifact is requested;
- who or what the target is;
- the target's role inside that artifact;
- what factual claims the user actually supplied;
- what visual transformations are allowed;
- what plausible but unsupported meanings must be blocked.

A request for creative photos of Netally means Netally is the photographed
person. It does not mean she is a photographer, owns a photography business,
offers services, needs a portfolio, or is a personal brand.

In the default intent-first mode, the purpose library and raw source prompts are
retrieval material, not provider instructions. Do not send a raw site case or
raw catalog prompt to Grok or Codex in that mode. The explicit `full-library`
  and `full-templates` modes are the exceptions. The first preserves each
  authoritative site-case prompt after a fixed, narrowly scoped person or
  explicit-placeholder substitution directive. The second preserves every queue-ready English template verbatim
after one fixed target-instantiation directive. Use either only when source
fidelity and exhaustive one-source-per-output coverage are the user's
controlling intent.

One creative plan item equals one provider prompt and one output file. For a
single-frame request, never create a collage, grid, sheet, board, multiple
panels, or multiple versions inside the canvas unless the authoritative source
case or template explicitly requests that topology in an exhaustive mode.

## Defaults

- Root: derived from the tracked skill package; override with `--root`
- Targets: ALVOS/<target>
- Catalog: PROMPTS/catalog.json
- Purpose library: PROMPTS/site-library
- Runner: scripts/image_production_factory.py
- Providers: Grok and Codex
- References: at most three real source images under the selected target
- Output: ALVOS/<target>/PRODUCOES/FOCUS-SLUG
- Resume: enabled

## Exhaustive source-faithful mode

Use this mode only when the user explicitly asks to run the complete source
library without creative-plan selection or prompt recomposition.

    python "<skill-dir>\scripts\image_production_factory.py" full-library --target "<target>" --focus "biblioteca-fonte-fiel-v6" --root "<ImageGenSource-root>" --batch all --providers both --dry-run

The authoritative set is the current pinned `PROMPTS/site-library` snapshot.
The runner requires the manifest count, `cases.json.total_cases`, and the actual
array length to agree; IDs must be unique integers but may be sparse. It derives
deterministic batches of 20 from that validated snapshot.
Each provider receives identical prompt bytes. Reference images are routed per
item: they are attached only when the source requests a visible person or an
explicit target placeholder.
The source prompt remains verbatim after a fixed instruction with one permitted
semantic substitution: a requested visible central person's identity becomes
the selected target, grounded by the reference. Products, brands, interfaces,
places, objects, events, visible copy, statistics, composition, style, and all
other requirements remain as written. A source without a visible person or
explicit target placeholder runs unchanged and must not acquire the target.
Any source prompt that exceeds a provider limit is compacted only outside
quoted strings. If the complete non-whitespace source still cannot fit, the
run fails closed before generation; source-faithful mode never truncates or
silently summarizes it.

Generate a reviewed batch with `--batch N` and without `--dry-run`. Resume is
allowed only when the schema-2 report entry is bound to the current prompt,
ordered references, and decodable output by SHA-256.

For an exhaustive run of all queue-ready templates in
`PROMPTS/catalog.json`, use:

    python "<skill-dir>\scripts\image_production_factory.py" full-templates --target "<target>" --focus "templates-fonte-fieis-v2" --root "<ImageGenSource-root>" --batch all --providers both --dry-run

The runner validates the declared queue-ready count and derives deterministic
batches of 20. It reads each authoritative English template file, preserves it
verbatim, and adds a fixed directive requiring every placeholder to be
instantiated for the selected target from real reference images. Generate a
reviewed batch with `--batch N` and without `--dry-run`.

## Selected source-faithful mode

Use this mode when the user explicitly wants a bounded number of real site
prompts instead of semantic recomposition or exhaustive coverage. The host must
inspect and explicitly select 1-20 compatible case IDs. The runner preserves
each selected authoritative source prompt under the same source-fidelity,
target-adaptation, reference-routing, SHA-256, resume, and provider-parity
contracts as `full-library` mode.

    python "<skill-dir>\scripts\image_production_factory.py" selected-library --target "<target>" --focus "<focus>" --root "<ImageGenSource-root>" --case-ids "510,444" --providers both --dry-run

Generate without `--dry-run`, inspect every output, write `VISUAL_REVIEW.json`,
then verify with:

    python "<skill-dir>\scripts\image_production_factory.py" verify-selected-library --target "<target>" --focus "<focus>" --root "<ImageGenSource-root>" --providers both

The selected manifest must report every source prompt as preserved verbatim or,
only when required by the 8,000-character provider limit, with all
non-whitespace source content preserved. Case-replacement payloads are not
supported; target adaptation may add constraints while the complete source
prompt remains in the provider payload.

If `ALVOS/<target>/SOURCE-ADAPTATION.md` exists, all source-faithful modes append it to the
fixed prefix and record its path and SHA-256 in the manifest. Use it for
target-specific closed rosters, verified facts, identity rules, and forbidden
claims that cannot be inferred safely from references alone.

Do not use PROMPTS, PRODUCOES, provider queues, vendor, node_modules, or old
generated outputs as source references.

## Workflow

### 1. Parse the invocation

Resolve target and focus from the current request. Ask only if a missing value
cannot be inferred safely. Do not silently substitute another target.

Inspect:

    python "<skill-dir>\scripts\image_production_factory.py" inspect --target "<target>" --focus "<focus>" --root "<ImageGenSource-root>"

The result exposes references, the 17 purposes, template semantics, creative
plan schema, and exact contract paths.

### 2. Recognize and review intent

Read templates/intent-contract.example.json and create the run's
intent-contract.json with schema_version 2.

Choose:

- output_purpose from the purpose taxonomy;
- output_topology from the requested artifact;
- output_count from the user's wording;
- text_policy from the artifact;
- exact compatible catalog IDs;
- must_not_infer terms for likely unsupported interpretations.

For a person, select explicit template IDs. Do not enable the entire catalog by
habit. Keep all profession, business, and brand flags false unless the user
explicitly made or authorized that claim.

Compare every semantic field against the current user request. Set reviewed=true
only after that comparison.

### 3. Retrieve by purpose, then inspect

Use the complete installed style library:

    python "<gpt-image-2-style-library-skill-dir>/scripts/query_style_library.py" search --query "<visual need>" --purpose "<purpose>" --topology "<topology>" --target-kind "<target kind>" --text-policy "<policy>" --limit 12

Select one to three compatible case IDs per planned image. Search results are
creative mechanisms to inspect, not text to execute. Use show for the chosen
cases only. Extract the complete compatible case-level DNA: artifact, premise,
narrative or transformation, subject-environment relationship, composition and
topology, camera, light and color, materials and texture, atmosphere and motion,
text hierarchy, and distinctive mechanism. Preserve compatible unusual props,
settings, wardrobe categories, and narrative devices when they give the case
its identity. Replace a literal only when it conflicts with current intent,
asserts an unsupported fact, carries an unauthorized identity/brand/copyright
element, or is incidental rather than distinctive. Remove brand, business,
biographical, pricing, packaging, and seller claims without flattening the
visual premise. Adapt source copy to the current request's language and facts;
preserve its hierarchy and function, not unrelated wording.

Select templates by compatible_purposes, output_topology, text_policy, and
target_kinds. The safe visual_recipe states what capability may cross into the
compiled prompt.

### 4. Inspect real references

Use view_image on the primary reference and up to two supporting references.

For a person, record only visible stable identity anchors. For a product,
interface, place, or brand, record geometry, palette, materials, typography,
and other visible anchors. Do not identify unknown people or infer biography
from appearance.

### 5. Initialize and author the creative plan

Initialize:

    python "<skill-dir>\scripts\image_production_factory.py" init --target "<target>" --focus "<focus>" --root "<ImageGenSource-root>"

Refine production-brief.json. Its mirrored intent fields and template lists must
match the reviewed contract exactly.

Write a complete creative_plan with exactly output_count items. Every item needs
a distinct scene and a concrete action, composition, camera, lighting, styling,
palette, mood, style direction, aspect ratio, avoid list, template ID, and one
to three compatible case IDs.

Synthesize each direction for this session. Do not mechanically fill source
template slots. Do not copy the selected cases.

### 6. Compile and audit without API calls

Run:

    python "<skill-dir>\scripts\image_production_factory.py" run --target "<target>" --focus "<focus>" --root "<ImageGenSource-root>" --providers both --dry-run

Require:

- queue count equals output_count;
- distinct_scenes equals output_count;
- one distinct prompt hash per item;
- both raw provider-payload flags are false;
- must_not_infer_literals_in_provider_payload is false;
- Grok and Codex prompt files match byte for byte;
- each single-frame prompt asks for exactly one standalone image;
- no positive direction asserts a blocked profession, business, brand, or
  literal source-example subject;
- no raw case or catalog prompt appears in provider text.

Fix the intent or plan at its source. Never weaken a guard merely to pass.

### 7. Generate when production is authorized

If the user requested actual production, run:

    python "<skill-dir>\scripts\image_production_factory.py" run --target "<target>" --focus "<focus>" --root "<ImageGenSource-root>" --providers both

Grok and Codex receive the same compiled image prompt and the same references.
The current runner executes Grok first and Codex second. The queues are not
network-parallel; each is sequential and resumable.

Credentials are read internally from active local 9Router connections. Never
print or serialize tokens.

An existing image is skipped only when Pillow can fully decode it and its
schema-2 provider report matches the current prompt SHA-256, ordered reference
SHA-256 list, and output SHA-256. Do not regenerate successful outputs without
a user request.

### 8. Inspect every output and verify

Mechanical completion is not visual success. Inspect every requested image when
the batch has up to 20 outputs. Compare each output with:

- the source reference or product anchors;
- the item-specific direction;
- output topology;
- text policy;
- original intent and blocked inferences.

Write VISUAL_REVIEW.json using templates/visual-review.example.json. Mark a
result accepted only when every applicable criterion passes. Include concise,
specific notes and bind each review entry to the exact prompt, ordered
references, and inspected output hashes.

Verify:

    python "<skill-dir>\scripts\image_production_factory.py" verify --target "<target>" --focus "<focus>" --root "<ImageGenSource-root>"

verify exits with status 2 until both provider files/reports and the complete
semantic visual review pass.

## Failure handling

- Missing target/reference/library/contract: stop and report the exact missing
  prerequisite.
- Contract or creative-plan violation: fix the semantic source, not the
  validator.
- 401 or 403: stop that provider and reconnect OAuth.
- 429: wait and resume; do not start duplicate processes.
- Timeout or network failure: resume; successful files remain skipped.
- Moderation block: record it; do not evade safeguards.
- Identity drift or wrong topology: reject in VISUAL_REVIEW and revise that
  item's creative plan before regeneration.

## Netally regression case

For “Faça fotos criativas variadas da Netally”:

- target_kind: person
- subject_role: person being photographed
- output_purpose: editorial-portrait
- output_topology: single-frame
- text_policy: forbidden
- catalog template: a compatible photography template
- one distinct plan item and file for each requested portrait
- no photographer, café/barista, business, portfolio, service, character-sheet,
  collage, or raw example content

Both provider queues must receive the same fresh item-specific prompts. Different
providers may render them differently, but neither provider is responsible for
recognizing the user's intent.

## Completion

For a production request, completion requires generated files, provider reports,
per-output visual inspection, and verify complete=true. For a test or dry-run
request, completion requires the requested diagnostic evidence and must clearly
state that no images were generated.
