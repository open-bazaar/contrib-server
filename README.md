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

A module with a long list can load the shared `window-list.js` asset:

```html
<script src="{{ asset('window-list.js', 'server') }}"></script>
<div data-window-list=".row">
  <!-- Direct child rows, followed by the module's usual htmx paging link. -->
</div>
```

The list keeps the loaded rows' HTML and measured heights, mounting only the
viewport and nearby rows. Its scroll container may be the list itself or a
scrolling ancestor. Give the list `overflow-anchor: none`; the component holds
the row being read when measurements change. Rows are in block flow, with their
vertical margins included in their height.

The module keeps its paging URLs and triggers. Appended pages are taken in after
the htmx swap; replacing a list releases the previous measurements and observers.
The bubbling `bazaar:window` event lets the page mark its current selection when
rows are restored.
