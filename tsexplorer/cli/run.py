import sys
import argparse
import pathlib
import warnings


def _get_save_location(*_):
    '''
    Checks, and prints out the directory location where the data will be
    stored to.
    '''
    from tsexplorer.utils.misc import get_user_data_directory
    data_dir = get_user_data_directory()
    print(f"{data_dir}")


def _get_template_config(known_args: argparse.Namespace, *_):
    '''
    Loads and dumps the template configuration file. If no target file is
    specified, the config will be dumped to standard output.

    Parameters
    ----------
    known_args: argparse.Namespace
        The user specified command-line arguments
    '''
    try:
        from tsexplorer.metadata import TEMPLATE_CONFIG_PATH
    except ImportError:
        warnings.warn(
                f"relative import failed, $PATH: {sys.path}", RuntimeWarning
        )
        raise
    from ruamel.yaml import YAML

    yaml = YAML(typ="rt")  # Using round-trip mode preserves the comments
    with TEMPLATE_CONFIG_PATH.open('r') as ifstream:
        config = yaml.load(ifstream)

    if known_args.out is None:
        yaml.dump(config, sys.stdout)
    else:
        with known_args.out.open('w') as ofstream:
            yaml.dump(config, ofstream)


def _run_gui(known_args: argparse.Namespace, extra_args: argparse.Namespace):
    '''
    Runs the actual application with the GUI. This is the main entry point
    for the application runtime.

    Parameters
    ----------
    known_args: argparse.Namespace
        The parsed arguments that were known to the parser.
    extra_args: argparse.Namespace
        The arguments that were given in the command-line, but were unknown
        to the parser. These are assumed to be arguments to QT, and thus passed
        to the application as is
    '''
    try:
        import tsexplorer
    except ImportError:
        warnings.warn(
                f"Relative import failed, $PATH: {sys.path}", RuntimeWarning
        )
        raise

    _override_rcparams(known_args)
    # Override the RCPARAM values with the values from the command-line
    appl = tsexplorer.app.Application(
            known_args.config_file, extra_args
    )
    appl.run_to_completion()


def _get_version() -> str:
    '''Tries to extract the version from the application'''
    try:
        import tsexplorer
    except ImportError:
        warnings.warn(
                f"Relative import failed, $PATH: {sys.path}", RuntimeWarning
        )
        raise
    else:
        return tsexplorer.__version__


def _override_rcparams(args: argparse.Namespace):
    '''
    Updates the rc-params of the application using user defined options,
    if any were set.

    Parameters
    ----------
    args: argparse.Namespace
        The arguments given by the user.
    '''
    try:
        from tsexplorer import defaults
    except ImportError:
        warnings.warn(
                f"Relative import failed, $PATH: {sys.path}", RuntimeWarning
        )
        raise

    payload = {}
    if args.label_font_size is not None:
        payload["label-font"] = {"size": args.label_font_size}

    if args.label_font_color is not None:
        if "font" not in payload:
            payload["label-font"] = {}
        payload["label-font"].update({"color": args.label_font_color})

    if args.app_font_size is not None:
        payload["application-font"] = {"size": args.app_font_size}

    if args.app_font_color is not None:
        if "application-font" not in payload:
            payload["application-font"] = {}
        payload["application-font"].update({"color": args.app_font_color})

    if args.tick_font_size is not None:
        payload["tick-font"] = {"size": args.tick_font_size}

    if len(payload) != 0:
        defaults.update_rcparams(payload)


def _add_default_params(group):
    '''
    Adds the common parameters to the given argument parser group
    '''
    group.add_argument(
            "--config-file", type=str, default="user_config.yml",
            help="Path to the configuration file (.yml). Default %(default)s",
            metavar="config-file"
    )
    group.add_argument(
            "-v", "--version",
            help="Show the version of the installed program",
            action="version", version="%(prog)s " + _get_version()
    )


def _add_visual_args(group):
    '''
    Add common arguments that control the visual appearance to the given
    argument parser group
    '''

    group.add_argument(
            "--app-font-size", type=str, default=None,
            help=("The font-size used for the application elements "
                  "(labels, buttons etc). If not set, automatically selects "
                  "a font-size. Default %(default)s")
    )

    group.add_argument(
            "--app-font-color", type=str, default=None,
            help=("The color used to render text in application elements "
                  "(labels, buttons, etc.). If not set, automatically selects "
                  "a suitable color. Default %(default)s")
    )

    group.add_argument(
            "--label-font-size", type=str, default=None,
            help=("The font-size used in data displaying components "
                  "(figure labels, axis labels etc). If not set, a "
                  "predetermined value is used. Default %(default)s")
    )

    group.add_argument(
            "--label-font-color", type=str, default=None,
            help=("The color used to render text in data displaying "
                  "components (figure labels, axis labels etc). If not set, "
                  "a predetermined value is used. Default %(default)s")
    )

    group.add_argument(
            "--tick-font-size", type=str, default=None,
            help=("The font-size used to render ticks, and tick-labels in "
                  "data displaying components. If not set, a predetermined "
                  "value is used. Default %(default)s")
    )


def _get_parser():
    '''Create argument parser for passing a config file path'''
    parser = argparse.ArgumentParser(
            prog="TSExplorer",
            description="GUI tool for time-series data annotation and exploration"
    )

    default_args = parser.add_argument_group("Common arguments")
    _add_default_params(default_args)
    visual_args = parser.add_argument_group("Visual arguments")
    _add_visual_args(visual_args)
    parser.set_defaults(func=_run_gui)

    # Create sub-parsers for additional commands
    subparsers = parser.add_subparsers()

    # Parser for starting the application
    app_parser = subparsers.add_parser(
            "run-gui", help="Run the data annotation and exploration tool"
    )
    default_arg_group = app_parser.add_argument_group("Common arguments")
    _add_default_params(default_arg_group)
    visual_arg_group = app_parser.add_argument_group("Visual arguments")
    _add_visual_args(visual_arg_group)
    app_parser.set_defaults(func=_run_gui)

    # Parser for getting the save location
    config_parser = subparsers.add_parser(
            "get-save-location",
            help="Prints out the location where the data is stored"
    )
    config_parser.set_defaults(func=_get_save_location)

    # Parser for loading and printing a default configuration file
    template_config_parser = subparsers.add_parser(
            "generate-config",
            help=("Generates a template configuration file which contains all "
                  "the possible options, and explanations of the options")
    )
    template_config_parser.add_argument(
            "-o", "--out", type=pathlib.Path, default=None,
            help=("The path where the template will be written to. If not "
                  "set, the config will be printed to stdout")
    )
    template_config_parser.set_defaults(func=_get_template_config)
    return parser


def main():
    parser = _get_parser()
    # Parse only the known arguments, and pass others to Qt
    parsed, args = parser.parse_known_args()
    parsed.func(parsed, args)
