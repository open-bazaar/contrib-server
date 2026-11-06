# bazaar-contrib-server

The Bazaar Compute server itself: the shell around every module, with its sidebar, settings page and update bus, and two themes, the night market and the morning market.

```toml
[[contribs]]
package = "bazaar-contrib-server~=0.3.0rc3"
[[contribs.enabled]]
entry = "server"
[[contribs.enabled]]
entry = "server-theme-night"
[[contribs.enabled]]
entry = "server-theme-day"
```

A contrib accepts `SERVER` to serve its pages and API in the shell, and `THEME` to bring a theme. Pages answer once a login contrib such as `bazaar-contrib-server-access` is enabled.
