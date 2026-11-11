import QtQuick
import Quickshell
import Quickshell.Io
import "common"
import "land"
import "starmap"

ShellRoot {
    id: shell
    property bool wallpaperVisible: true
    property bool themeActive: false
    FileView {
        path: Quickshell.env("HOME") + "/.local/state/omarchy/current/theme.name"
        watchChanges: true
        printErrors: false
        onLoaded: shell.themeActive = text().trim() === "no-mans-sky"
        onLoadFailed: shell.themeActive = false
        onFileChanged: reload()
    }
    onThemeActiveChanged: {
        if (!themeActive) {
            overview.active = false
            palettePending = false
            paletteTimer.stop()
        }
    }
    property bool profiling: false
    property var lastPerformance: ({})
    Variants {
        model: Quickshell.screens
        Land { required property var modelData; screen: modelData; visible: shell.wallpaperVisible && shell.themeActive }
    }
    LazyLoader {
        id: overview
        StarMap {
            profiling: shell.profiling
            onDone: { shell.lastPerformance = performance(); overview.active = false }
        }
    }
    function toggleMap() {
        if (!themeActive) return
        if (overview.active) overview.item.close()
        else { Ui.target = Hypr.focusedScreen(); overview.active = true }
    }
    property bool palettePending: false
    Connections {
        target: World
        function onPaletteChanged() {
            if (shell.themeActive) { shell.palettePending = true; paletteTimer.restart() }
        }
    }
    Connections {
        target: Ui
        function onHoldThemeChanged() { if (!Ui.holdTheme && shell.palettePending) paletteTimer.restart() }
    }
    Timer {
        id: paletteTimer
        interval: 400
        onTriggered: {
            if (!shell.themeActive || Ui.holdTheme || !shell.palettePending || paletteSync.running) return
            shell.palettePending = false
            if (Quickshell.env("NMS_SYNC_PALETTE") === "1") paletteSync.running = true
        }
    }
    Process {
        id: paletteSync
        command: [Quickshell.env("HOME") + "/.local/bin/omarchy-nms", "sync-palette"]
        stderr: StdioCollector { onStreamFinished: if (text.trim()) console.warn("Palette sync:", text.trim()) }
        onExited: { if (shell.palettePending) paletteTimer.restart() }
    }
    IpcHandler {
        target: "nms"
        function toggle(): void { shell.toggleMap() }
        function close(): void { if (overview.active) overview.item.close() }
        function abort(): void { overview.active = false }
        function profile(enabled: bool): void { shell.profiling = enabled }
        function performance(): string { return JSON.stringify(overview.active ? overview.item.performance() : shell.lastPerformance) }
        function world(): void { if (shell.themeActive && !overview.active) World.hop(true) }
        function wallpaper(show: bool): void { shell.wallpaperVisible = show }
        function visit(workspace: int): bool {
            if (!overview.active || overview.item.busy) return false
            const system = overview.item.used.find(s => s.id === workspace)
            if (!system) return false
            overview.item.warp(system)
            return true
        }
        function status(): string {
            const map = overview.active ? overview.item : null
            return JSON.stringify({ map: overview.active, phase: !map ? "desktop" : map.busy ? "transition" : "flight",
                system: map?.sel?.id ?? 0, systems: map?.used?.length ?? 0,
                position: map ? [map.px, map.py, map.pz] : [], wallpaper: shell.wallpaperVisible && shell.themeActive,
                themeActive: shell.themeActive, hue: World.hue, seed: World.landSeed })
        }
    }
}
