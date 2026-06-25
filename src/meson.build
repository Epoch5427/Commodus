pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'commodus'

gnome = import('gnome')
python = import('python')

# --- Blueprint setup ---
blueprint_compiler = find_program('blueprint-compiler', required: true)   # NEW

# Add your .blp files here
blueprint_sources = files('window.blp')                              # NEW

# Compile .blp → .ui
ui_files = custom_target('ui',                                            # NEW
  input: blueprint_sources,                                               # NEW
  output: 'window.ui',                                                    # NEW
  command: [blueprint_compiler, 'compile', '@INPUT@'],                    # NEW
  capture: true                                                           # NEW
)                                                                         # NEW
# --- end Blueprint setup ---

gnome.compile_resources('commodus',
  'commodus.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  dependencies: ui_files,   # NEW: ensure .ui is built before resources
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
]

install_data(commodus_sources, install_dir: moduledir)
