# ElevenLabs owns the phone call (native Twilio integration)

The pilot Twilio number is imported into ElevenLabs, which runs the conversation and performs transfers with its built-in `transfer_to_number` tool. We rejected a backend-owned call (Twilio TwiML + ElevenLabs register-call) even though only that can detect an unanswered transfer, retry, or return the caller to the agent — the extra telephony code wasn't worth it for the pilot, and cost isn't a constraint yet.

## Consequences

- An unanswered transfer (to the office line, including emergencies) is invisible to us: the foreman may hit voicemail or dead air. Accepted. Mitigation: the office is pre-notified by dashboard pop-up + SMS before every transfer, and emergencies alert all coordinators.
- Unrostered callers can't be refused before the agent answers; the call-start webhook overrides the first message and the agent ends the call.
- If the call-start webhook is down, ElevenLabs may drop the call. Mitigated by an always-on backend and uptime alerting.
- Revisit (switch to backend-owned call legs) if unanswered transfers show up in the pilot failure log.
