// 点工具栏图标 → 打开侧边栏。没有别的后台逻辑：
// 插件不定时、不自动访问任何站点，一切动作由用户在侧边栏发起。
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
