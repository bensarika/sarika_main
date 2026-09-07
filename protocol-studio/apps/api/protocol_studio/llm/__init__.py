"""Model gateway: provider-independent access to LLMs with fail-closed data-class policy.

    keys.py       encrypt/decrypt provider API keys at rest (Fernet, key derived from PS_SECRET_KEY)
    providers.py  ``Provider`` protocol + adapters (OpenAI Responses API today; Grok/Muse are one class each)
    gateway.py    ``call()``: resolves config + policy, calls the provider, records an ``AiCall`` — the
                  *only* code path allowed to send document text off the box
    prompts.py    prompt builders for revise / ask, kept deterministic so tests can pin them

Invariants (docs/01_architecture.md §7):
- A provider receives text of data class ``c`` only if an admin approved (provider, c);
  ``public`` is allowed for any enabled provider. Anything else raises ``PolicyBlockedError``.
- Model output is always a *proposal* (``propose_text``) with deterministic factual-change
  checks attached; it never edits the live document.
- Prompt text is never persisted; ``AiCall`` records tokens, latency, purpose only.
"""
