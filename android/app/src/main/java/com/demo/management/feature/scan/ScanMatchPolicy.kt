package com.demo.management.feature.scan

import com.demo.management.data.round3.ScanMatch

sealed interface ScanAction {
    data class Open(val match: ScanMatch) : ScanAction
    data class Select(val matches: List<ScanMatch>) : ScanAction
    data object ManualSearch : ScanAction
}

fun scanAction(matches: List<ScanMatch>): ScanAction = when (matches.size) {
    0 -> ScanAction.ManualSearch
    1 -> ScanAction.Open(matches.first())
    else -> ScanAction.Select(matches)
}
