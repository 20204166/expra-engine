"""PySide6 (Qt Widgets) frontend for the Expra editor.

The editor's behaviour lives in toolkit-independent modules: window logic
(``editor.window_core``), inspector, asset browser, viewport and export-dialog
logic (``editor.*_core``), the hierarchy row projection, dialog protocol,
project workflow and every editor command. This package supplies the Qt
presentation of those pieces:

  main_window.py        QMainWindow shell, docks, native Qt menus, shortcuts
  toolbar.py            toolbar built from the same contributions
  hierarchy.py          hierarchy panel (QTreeWidget via ``tree_adapter``)
  inspector.py          inspector panel (QLineEdit/QCheckBox via ``field_vars``)
  asset_browser.py      asset browser panel
  viewport.py           viewport hosting a ``QtCanvas``
  canvas.py             QGraphicsView exposing the canvas surface ViewportCore draws to
  console.py            console panel
  export_dialog.py      export dialog
  normal_map_preview.py normal-map preview window
  dialogs.py            QtDialogProvider (QMessageBox/QFileDialog/QInputDialog)
  delivery.py           QtDeliveryQueue (worker thread -> Qt main thread)
  timer_delivery.py     QtTimerDelivery
  runtime_preview.py    QtRuntimePreviewLoop
  image_bridge.py       PIL/pygame -> QImage/QPixmap, ``QtEditorImage``
  action_widget.py      semantic Qt action-control adapter
  theme.py              dark palette from the shared design tokens
  app.py                ``run_qt_editor`` (the ``expra-editor`` entry point)

Nothing in core, runtime, filesystem or export imports this package
(see ``tests/test_gui_boundaries.py``).
"""
