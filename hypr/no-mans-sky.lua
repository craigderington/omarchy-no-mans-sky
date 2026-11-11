-- Loaded by the user's bindings.lua. No monitor or workspace rules are changed.
local command = string.format("%q", os.getenv("HOME") .. "/.local/bin/omarchy-nms")
o.bind("SUPER + ALT + N", "No Man's Sky star map", command .. " map")
o.bind("SUPER + ALT + W", "No Man's Sky new world", command .. " world")
o.bind("SUPER + ALT + ESCAPE", "Close No Man's Sky star map immediately", command .. " abort")

-- Theme-specific appearance is applied after the user's looknfeel.lua loads.
hl.on("config.reloaded", function()
  local file = io.open(os.getenv("HOME") .. "/.local/state/omarchy/current/theme.name", "r")
  if not file then return end
  local theme = file:read("*l")
  file:close()
  if theme == "no-mans-sky" then
    hl.config({
      general = { border_size = 1 },
      decoration = {
        rounding = 2,
        active_opacity = 0.85,
        inactive_opacity = 0.75,
      },
    })
  end
end)
