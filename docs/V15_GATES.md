# V15 Deployment Gates

V15 is allowed to progress from mathematical design to Solidity only when all of the following remain true:

1. frozen V13.1 baseline is untouched;
2. Economic HardNAV and RiskNAV are separate;
3. own synthetics have zero Economic HardAsset value;
4. every external liability is registered once;
5. synthetic partitions reconcile exactly;
6. pure gradient has zero Economic HardNAV effect;
7. atomic QE/QT ends supply-neutral;
8. realized-profit tax uses actual route profit;
9. robust gain includes oracle uncertainty and system-paid costs;
10. post-state K and STS satisfy mode floors;
11. RED/ORANGE cannot initiate new risk expansion;
12. defensive actions have bounded HardNAV cost and improve/restore solvency;
13. capital contributions cannot be booked as operating revenue;
14. revenue waterfall cannot exceed distributable hard PnL;
15. state is re-quoted after every accepted route;
16. common-mark conservation regression closes within integer tolerance;
17. aligned-market control has no accepted protocol-accretive executable route;
18. stale/untrusted oracle state fails closed;
19. bridge liabilities and claims are included in stress accounting;
20. a failed postcondition reverts the entire transition atomically.

No mainnet or fork deployment gate is considered passed by Python arithmetic alone. Solidity compile, unit tests, invariant/fuzz tests, and an archival fork run remain mandatory later stages.
