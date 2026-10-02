pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'commodus'

gnome = import('gnome')
python = import('python')

# --- Blueprint setup ---
blueprint_compiler = find_program('blueprint-compiler', required: true)

# Add your .blp files here
blueprint_sources = files(
  'UI/shortcuts-dialog.blp',
  'UI/window.blp',
  'UI/import_dialog.blp',
  'UI/branch_dialog.blp',
)

# Compile .blp → .ui
ui_files = custom_target('ui',
  input: blueprint_sources,
  output: [
    'shortcuts-dialog.ui',
    'window.ui',
    'import_dialog.ui',
    'branch_dialog.ui',
  ],
  command: [
    blueprint_compiler,
    'batch-compile',
    '@OUTDIR@',
    meson.current_source_dir() / 'UI',
    '@INPUT@',
  ],
)
# --- end Blueprint setup ---

gnome.compile_resources('commodus',
  'commodus.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  source_dir: [
    meson.current_source_dir(),          # Looks in src/
    meson.current_build_dir(),           # Looks in build/src/ (for window.ui)
    meson.project_build_root() / 'data', # Looks in build/data/ (for metainfo.xml)
  ],
  dependencies: [
    ui_files,
    appstream_file,                      # Ensures metainfo is generated first
  ],
)

conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('VERSION', meson.project_version())
conf.set('localedir', get_option('prefix') / get_option('localedir'))
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'commodus.in',
  output: 'commodus',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x'
)

commodus_sources = [
  '__init__.py',
  'main.py',
  'window.py',
  'branch_dialog.py',
  'import_dialog.py',
  'diagnostics.py',
  'scheduler_runner.py',
  'timetable_view.py',
  'database_service.py',
]

install_data(commodus_sources, install_dir: moduledir)
