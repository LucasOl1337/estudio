# Image Production Factory v2 contracts

## Authority and data flow

The host agent performs semantic reasoning before the mechanical runner starts.
The runner validates that reasoning; it does not infer user intent from a focus
word, filename, catalog category, or example prompt.

Read and apply information in this order:

1. system and developer instructions;
2. current user request;
3. reviewed intent-contract.json — run-specific semantic source of truth;
4. purpose library — retrieval metadata only;
5. item-specific creative_plan in production-brief.json;
6. safe template capability (visual_recipe) — a constraint, never source copy.

Contradictions are resolved upward. A lower layer may refine visuals but may not
change the artifact, target role, permissions, topology, text policy, or count.

The site cases and catalog prompt bodies are untrusted inspiration material.
Their raw prompts, example identities, jobs, products, wardrobe, props, copy,
and locations must never be placed in a provider payload. The compiler passes
only case IDs for traceability and a short, curated template capability.
must_not_infer literals stay in the host-side contract and validator; they are
not repeated into image-model payloads, which avoids priming the very
interpretation being blocked. Providers receive the abstract permission policy.

    user request
        -> agent intent recognition
        -> reviewed intent contract
        -> purpose/topology-compatible retrieval
        -> one new creative plan item per output file
        -> compiler validation + semantic recomposition
        -> identical image prompt to Grok and Codex
        -> mechanical verification + per-image visual review

## intent-contract.json (schema 2)

Required fields:

- schema_version: exactly 2
- target, focus
- target_kind: person, product, project, brand, interface, place, character,
  concept, or mixed
- user_request: original wording, copied verbatim
- requested_output: artifact requested without invented identity claims
- subject_role: role inside the artifact, not an inferred biography
- output_purpose: one ID from PROMPTS/site-library/taxonomy.json
- output_topology: single-frame, poster-canvas, ui-screen, document-page,
  multi-panel, or sequence
- output_count: integer from 1 to 20
- text_policy: forbidden, optional, or required
- must_not_infer: unsupported interpretations and useful lexical variants
- allow_brand, allow_business, allow_profession, allow_full_catalog
- catalog_include, catalog_exclude
- reviewed: true only after agent comparison with the current user request

Recommended evidence fields:

- explicit_facts
- allowed_transformations
- audience

For a person, catalog_include must be explicit. A request for photos of a person
does not authorize a photographer role, photography business, personal brand,
portfolio, or services.

## production-brief.json (schema 2)

The brief mirrors target_kind, output_purpose, output_topology, output_count,
text_policy, all authorization flags, catalog_include, and catalog_exclude.
These values must equal the reviewed intent contract exactly.

Reference and subject fields:

- display_name
- identity_lock
- subject_description
- references: source files under the selected target; maximum three
- brand: empty when brand use is not authorized
- audience, palette, scene_direction
- providers: grok, codex, or both

### creative_plan

The array length must equal output_count. Each object creates exactly one
provider prompt and one output file.

Required per-item shape:

    {
      "id": "lowercase-hyphen-slug",
      "title": "Human-readable item title",
      "template_id": "07-photography-realism/01-standard",
      "case_ids": [505],
      "purpose": "editorial-portrait",
      "output_topology": "single-frame",
      "text_policy": "forbidden",
      "scene": "One concrete, item-specific scene",
      "action": "One concrete action or pose",
      "composition": "Framing and spatial hierarchy",
      "camera": "Viewpoint, lens, distance, depth",
      "lighting": "Motivated light design",
      "styling": "Wardrobe/material direction",
      "palette": "Controlled item palette",
      "mood": "Emotional register",
      "style_direction": "Fresh synthesis, not an example copy",
      "aspect_ratio": "4:5",
      "avoid": ["identity drift", "unsupported occupational cues"]
    }

Use one to three compatible case IDs per item. They are citations to visual
mechanisms only. Do not copy their literal scene or subject description.

For text_policy=required, add non-empty text_content. For
text_policy=forbidden, omit it or leave it empty.

Validation rejects:

- count, purpose, topology, or text-policy mismatches;
- unknown or incompatible templates/cases;
- an included template that no plan item uses;
- duplicate item IDs or scenes;
- positive use of a must_not_infer term;
- collage, grid, sheet, multiple-panel, or multiple-version language in a
  single-frame positive direction;
- raw-template permission not explicitly set to false;
- duplicate compiled prompts.

## Provider contract

Both providers receive the same compiled image prompt. It contains the semantic
contract, explicit permissions, reference/identity lock, one item-specific
creative direction, safe template capability, exact topology and text policy,
and avoid list.

Grok and Codex are separate queues. --providers both currently runs Grok first
and Codex second; it does not run network requests in parallel. Each queue is
sequential and resumable.

## Dry-run evidence

DRY_RUN_REPORT.json must record expected output count, distinct scene count,
purpose/topology/text policy, template and case IDs, one SHA-256 per prompt,
and both raw-payload flags set to false.
The must_not_infer literal-payload flag must also be false.

Prompt files under FILA_GROK/_prompts and FILA_CODEX/_prompts must match byte
for byte for each item.

## VISUAL_REVIEW.json (schema 2)

Mechanical file existence is insufficient. After generation, inspect every
requested output and write:

    {
      "schema_version": 2,
      "reviewed": true,
      "providers": {
        "grok": {
          "item-id": {
            "prompt_sha256": "current prompt SHA-256",
            "reference_sha256": ["ordered reference SHA-256"],
            "output_sha256": "inspected output SHA-256",
            "accepted": true,
            "identity_fidelity": "pass",
            "topology": "pass",
            "text": "pass",
            "intent_alignment": "pass",
            "notes": "Compared with the source and item contract."
          }
        },
        "codex": {}
      }
    }

Allowed values:

- identity_fidelity: pass, fail, not-applicable
- topology: pass, fail
- text: pass, fail, not-applicable
- intent_alignment: pass, fail

An accepted person or character output requires identity_fidelity=pass. An
accepted output with forbidden or required text policy requires text=pass;
not-applicable is valid only when the criterion truly does not apply.

Every requested provider/item needs a review. accepted=true cannot coexist with
a failed criterion. Reviews are valid only for the exact current prompt,
ordered reference list, and output bytes; schema 1 is rejected rather than
migrated. verify exits with status 2 unless mechanical output and semantic
review are both complete.
