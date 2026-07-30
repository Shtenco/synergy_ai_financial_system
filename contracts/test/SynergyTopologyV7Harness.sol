// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {SynergyTopologyV7} from "../graph/SynergyGraphArbitrageV7.sol";

contract SynergyTopologyV7Harness is SynergyTopologyV7 {
    constructor(
        address wpol_,
        address usdt_,
        address participantRegistry_,
        address internalFactory_,
        address quickSwapFactory_,
        address positionManager_
    ) SynergyTopologyV7(
        wpol_,
        usdt_,
        participantRegistry_,
        internalFactory_,
        quickSwapFactory_,
        positionManager_
    ) {}

    /// @dev Test/fork inventory remains protocol inventory and is never external revenue.
    function mintInternalInventory(address to, uint256 synaAmount, uint256 synrAmount)
        external
        onlyAdmin
    {
        if (synaAmount > 0) syna.mint(to, synaAmount);
        if (synrAmount > 0) synr.mint(to, synrAmount);
    }

    function setRepresentativeInfrastructure(address account, bool enabled)
        external
        onlyAdmin
    {
        syna.setInfrastructure(account, enabled);
    }
}
