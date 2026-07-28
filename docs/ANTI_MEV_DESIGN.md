# Anti-MEV execution boundary

No contract can reliably identify every MEV bot or confiscate an uninvolved
address's funds. The implemented design instead uses enforceable controls:

1. solver routes are committed as hashes with a voluntary native-token bond;
2. reveal is allowed only after two blocks and expires after 120 blocks;
3. an expired commitment's bond can be moved to protocol treasury;
4. execution targets remain allowlisted and the settlement balance must grow;
5. integrated trade outputs vest for 24 hours, with a fixed burn sink on early exit;
6. private/builder submission or a batch auction should carry revealed execution.

The fixed burn sink removes the prior caller-controlled destination, and claimed
positions cannot be claimed twice. Slashing is limited to objective expiry of a
voluntary bond; it is not based on unverifiable claims that an address is a bot.

The deterministic model demonstrates that a known public route can have positive
sandwich value. A sealed route exposes no modeled pre-trade information, reducing
that value to zero; expired solver bonds are protocol revenue. Real builders can
still censor or leak bundles, so this is mitigation rather than complete immunity.

## Operating controls

Private order flow is recommended but not mandatory. Public-RPC execution must
use atomic policy consumption, per-leg minimum outputs, a short deadline,
protected-asset balance floors, codehash-pinned targets, TWAP bounds, daily
limits, and a post-trade settlement-profit check. These make a manipulated
transaction revert, but cannot prevent validators from censoring it.

`ProtocolTaxToken` is a migration reference with a uniform 20–30% treasury tax
and no transfer exemptions. This satisfies uniform treatment but does not detect
bots; it also taxes honest users, LP adds/removes, and every arbitrage hop. It
cannot be retrofitted into already deployed immutable tokens without migration.
