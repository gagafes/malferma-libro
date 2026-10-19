# Piper runtime and voice licensing evidence

Upstream research recorded on 2026-10-17 for Malferma Libro 0.1.0 is retained
for 0.1.1. This record distinguishes
the reader's GPL license, the separately installed Piper runtime, and each
voice model's upstream terms. It does not relicense downloaded or imported
models. No voice weights are included in the application source or Debian package.

The current application-only Debian package does not include Piper runtime
binaries. The earlier runtime bundle build scripts were not present in the
saved package and are not available in this recovered release. Optional
external-runtime installation remains supported; see [MANUAL.md](MANUAL.md)
and [PIPER_BUNDLE.md](PIPER_BUNDLE.md). No actual synthesis is claimed here.

## Runtime

The selected upstream runtime is **OHF-Voice Piper / piper-tts 1.8.0**,
licensed **GPL-3.0-or-later**. Its tagged
[package metadata](https://github.com/OHF-Voice/piper1-gpl/blob/v1.8.0/setup.py)
declares Python 3.9 or newer. [PyPI 1.8.0](https://pypi.org/project/piper-tts/1.8.0/)
publishes Linux x86_64 and aarch64 CPython stable-ABI wheels and lists Python 3.13.
Debian 13's Python 3.13 and glibc 2.41 match those wheel requirements, according
to the [Debian release notes](https://www.debian.org/releases/trixie/release-notes/whats-new.en.html).
This is a compatibility check of published metadata; installation and audible
synthesis were not tested in the build environment.

The upstream [README](https://github.com/OHF-Voice/piper1-gpl/blob/v1.8.0/README.md)
states that Piper embeds eSpeak NG for phonemization. Piper is the reader's sole
narration backend. Removing the reader's former separate eSpeak backend does
not remove components required by Piper itself. Runtime distributors must
preserve Piper's and its dependencies' applicable notices and source obligations.

The Debian package named [piper](https://packages.debian.org/trixie/piper) is a
gaming-mouse configuration utility. It is not this TTS runtime. Use the
`piper-tts` distribution in an isolated Python environment, following the
application installation guide; do not install `apt install piper` for narration.

## Per-voice review

Upstream's [voice documentation](https://github.com/OHF-Voice/piper1-gpl/blob/v1.8.0/docs/VOICES.md)
directs users to each voice's `MODEL_CARD` for licensing and training history.
A repository-wide MIT badge is not used to override a voice's individual
restrictions. The following table records the declarations in those cards.
Most cards place their license statement in a dataset section; that declaration
and the stated training history form this catalog's recorded basis. The three
high-quality Ukrainian models also have an explicit Apache-2.0 model grant
on their original author's pages.

| Model | Language | Upstream license declaration | Training evidence | Primary source |
| --- | --- | --- | --- | --- |
| `en_US-ljspeech-high` | en | Public domain | From scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/high/MODEL_CARD) |
| `en_US-libritts-high` | en | CC-BY-4.0 | From scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/libritts/high/MODEL_CARD) |
| `uk_UA-ukrainian_tts-medium` | uk | CC0-1.0 | From scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/uk/uk_UA/ukrainian_tts/medium/MODEL_CARD) |
| `uk_UA-lada-x_low` | uk | Apache-2.0 | From scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/uk/uk_UA/lada/x_low/MODEL_CARD) |
| `uk_UA-mykyta-high` | uk | Apache-2.0 | Explicit Apache-2.0 model grant by Roman Stasyshyn | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/uk/uk_UA/mykyta/high/MODEL_CARD) · [author](https://huggingface.co/RomanStasyshyn/uk_UA-mykyta-high) |
| `uk_UA-oleksa-high` | uk | Apache-2.0 | Explicit Apache-2.0 model grant by Roman Stasyshyn | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/uk/uk_UA/oleksa/high/MODEL_CARD) · [author](https://huggingface.co/RomanStasyshyn/uk_UA-oleksa-high) |
| `uk_UA-tetiana-high` | uk | Apache-2.0 | Explicit Apache-2.0 model grant by Roman Stasyshyn | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/uk/uk_UA/tetiana/high/MODEL_CARD) · [author](https://huggingface.co/RomanStasyshyn/uk_UA-tetiana-high) |
| `de_DE-mls-medium` | de | CC-BY-4.0 | From scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/de/de_DE/mls/medium/MODEL_CARD) |
| `fr_FR-mls-medium` | fr | CC-BY-4.0 | From scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/fr/fr_FR/mls/medium/MODEL_CARD) |
| `es_ES-carlfm-x_low` | es | Public domain | From scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/es/es_ES/carlfm/x_low/MODEL_CARD) |
| `it_IT-serena-medium` | it | CC-BY-4.0 | From scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/it/it_IT/serena/medium/MODEL_CARD) |
| `it_IT-serena-high` | it | CC-BY-4.0 | From scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/it/it_IT/serena/high/MODEL_CARD) |

“Public domain” is the upstream wording for LJ Speech and CarlFM. It is recorded
as `LicenseRef-Public-Domain` in research metadata; it is not silently changed
to a CC0 declaration. Preserve attribution and source links for CC-BY models;
retain the upstream cards and applicable license notices when distributing any
model. Apache-2.0 and CC0 models retain their own terms and are not covered by
the reader's GPL grant.

Multispeaker files include Ukrainian TTS (3 speakers), LibriTTS (904), German
MLS (236), and French MLS (125). These are model capabilities reported by
upstream cards, not a claim that the reader exposes every speaker as a separate
preset. Ukrainian TTS's card specifies text phonemes; its matching configuration
must be retained with the model.

## Immutable sources and integrity

The researched catalog uses repository `rhasspy/piper-voices` at commit
[`347893230ff234f23ea596edaef6b953745fb8d8`](https://huggingface.co/rhasspy/piper-voices/commit/347893230ff234f23ea596edaef6b953745fb8d8).
That commit adds the Serena models and includes the older models above.
For each model, its `.onnx`, matching `.onnx.json`, and `MODEL_CARD` are addressed
under the same immutable revision. Model SHA-256 values below were read from
upstream Git LFS pointers or Hugging Face's SHA-256 panels. They were not
calculated from model binaries downloaded in this build environment. Config
and model-card SHA-256 values were not independently fetched; none are invented.

| Model | ONNX SHA-256 | Bytes, where verified |
| --- | --- | --- |
| `en_US-ljspeech-high` | `5d4f08ba6a2a48c44592eed3ce56bf85e9de3dd4e20df90541ae68a8310c029a` | 114199011 |
| `en_US-libritts-high` | `9127a559e11603f10b366d1a20ac7426826081dbc521de4c2420c57728d73f0f` | 136673811 |
| `uk_UA-ukrainian_tts-medium` | `7920419ac5f6fd8b6450520f24b52ed5a319cb53dd018fbcd71c9e079cbac84f` | 76735663 |
| `uk_UA-lada-x_low` | `f8d015d3fc19ea6bd8ac3ca1fd0c0fbac5054c609599ee73799235fd2cf5c786` | 20628813 |
| `uk_UA-mykyta-high` | `081d253cd246d7d4d698c6dd147b74cad498dafd213527887a3a490519138243` | 114204024 |
| `uk_UA-oleksa-high` | `e5524d8d6b3685abd6daa616edae22c782b1eaa1541c0e5922183cf5f2d155b7` | not independently recorded |
| `uk_UA-tetiana-high` | `1206d8447b99632badeb63d6132241f76cf551874e5254eb8836db36aed7c85c` | 114204024 |
| `de_DE-mls-medium` | `69cd1d2aa5a35839a518966fcc4924b5f93e5f8c948ed0752b1a616ad53f65bf` | not independently recorded |
| `fr_FR-mls-medium` | `0ed223f78466917f2bae05ee90096ce69ab1fdeb251f55590d0e7422d234e162` | not independently recorded |
| `es_ES-carlfm-x_low` | `d69677323a907cd4963f42b29c20a98b5d6bfa7f3e64df339915e4650c00d125` | not independently recorded |
| `it_IT-serena-medium` | `3f1493311db17fec0e95cdf3c92f82b5006159b7743e057a749187469dfa7cf0` | 63511037 |
| `it_IT-serena-high` | `743240dae6ecab12cdc3eee9260cbf688a04e066775d0ce28b8007dad12f42d0` | 114199010 |

An unavailable exact byte count does not change the recorded model digest.
Downloads still require bounded file sizes, model digest verification, and
validation of the matching JSON configuration. A checksum proves integrity;
it does not establish licensing rights or audio quality.

## Excluded or unresolved candidates

The reviewed catalog excludes direct noncommercial restrictions, unknown
licenses, and declared ancestry whose free-use terms could not be established:

| Candidate | Recorded issue |
| --- | --- |
| `ru_RU-ruslan-medium` | [Card](https://huggingface.co/rhasspy/piper-voices/blob/main/ru/ru_RU/ruslan/medium/MODEL_CARD) names CC-BY-NC-SA-4.0. |
| `ru_RU-irina-medium` | [Card](https://huggingface.co/rhasspy/piper-voices/blob/main/ru/ru_RU/irina/medium/MODEL_CARD) lists an unknown dataset license and Lessac ancestry. |
| `ru_RU-dmitri-medium`, `ru_RU-denis-medium` | Own datasets are declared CC0, but both cards name Lessac as the parent. |
| `de_DE-thorsten-medium/high`, `fr_FR-siwis-medium`, `fr_FR-upmc-medium`, `es_ES-sharvard-medium`, `it_IT-paola-medium`, `pt_BR-faber-medium`, `pt_PT-tugão-medium` | Cards name Lessac ancestry; a free license for that complete lineage was not established. |
| `de_DE-thorsten-low`, `de_DE-kerstin-low`, `fr_FR-gilles-low`, `fr_FR-siwis-low`, `pt_BR-edresson-low` | Cards name Ryan ancestry; Ryan's [card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ryan/low/MODEL_CARD) declares CC-BY-NC-SA-4.0. |

Lessac's [linked corpus agreement](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html)
restricts use to research and excludes commercial speech-product uses.
This review does not decide how such dataset restrictions legally apply to
trained weights. It records that the uncertainty was not resolved, so those
models are not presented as cleared free downloads. Piper's maintainer
also declines to make a general determination about model-license inheritance
in the [upstream licensing discussion](https://github.com/rhasspy/piper/discussions/271).

No Russian or Portuguese model with sufficiently clear free terms was verified
for the curated download list during this review. Local ONNX model import can
still support those languages without redistributing a model or claiming its
license has been cleared. Importing a file does not grant rights in its model,
training data, or generated output; its owner's terms remain applicable.

## Review limits

Primary project, model-author, and model-card sources were inspected through
the web connector. Shell-network downloads were unavailable. No model was
installed, executed, listened to, or certified for pronunciation quality here.
The source package remains usable with optional Piper and independently
obtained models. This recovered release does not provide a Flatpak build
or bundled runtime. Retaining these research notes is not a new online
verification of model cards or a guarantee of pronunciation quality.
