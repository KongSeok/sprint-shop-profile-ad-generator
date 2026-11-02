# Luna v3 comparison

- v3-1: Codex independent 15-rule proposal (before the combined proposal).
- v3-2: user-supplied Claude 20-rule proposal; also installed as service copy_v2.txt.
- Four conditions: v3-1, v3-1 + examples, v3-2, v3-2 + examples.
- Shops: gold profiles 2, 8, 14; first menu, no extra features or this_time.
- Real OpenAI Responses API: gpt-6-luna, reasoning medium, default temperature, max output 4096.
- Existing v2 output schema and example selector unchanged; same selected example IDs across proposals.
- One call per condition and shop, no API retries. All 12 succeeded.
- Full system prompt, schema, input, output, usage and response IDs in each JSON.
- Estimated incremental cost USD 0.00845074 using prior comparison rates; not a billing statement.
- Full existing suite: 179 passed. Both prompt files loaded and service v2 equals v3-2.
- Manual review: cafe v3-2 without examples asks two questions; cafe Instagram outputs use ~습니다 despite haeyo guidance. Bakery copy sometimes narrows general afternoon sellout information to milk bread. Automatic warnings do not detect these issues.
- Single samples per condition are illustrative, not a statistically reliable ranking.
