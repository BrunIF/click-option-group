# -*- coding: utf-8 -*-

import typing as ty
import collections.abc as abc
import collections
import warnings

import click

from ._core import OptionGroup
from ._helpers import (
    get_callback_and_params,
    get_fake_option_name,
    raise_mixing_decorators_error,
)


class OptionStackItem(ty.NamedTuple):
    param_decls: ty.Tuple[str, ...]
    attrs: ty.Dict[str, ty.Any]
    param_count: int


class _NotAttachedOption(click.Option):
    """The helper class to catch grouped options which were not attached to the group

    Raises TypeError if not attached options exist.
    """

    def __init__(self, param_decls=None, *, option_decls, all_not_attached_options, **attrs):
        super().__init__(param_decls, expose_value=False, hidden=False, **attrs)
        self.option_decls = option_decls
        self._all_not_attached_options = all_not_attached_options

    def handle_parse_result(self, ctx, opts, args):
        self._raise_error(ctx)

    def get_help_record(self, ctx):
        self._raise_error(ctx)

    def _raise_error(self, ctx):
        options_error_hint = ''
        for option in reversed(self._all_not_attached_options[ctx.command.callback]):
            decls = option.option_decls
            options_error_hint += f'  {click.Option(decls).get_error_hint(ctx)}\n'
        options_error_hint = options_error_hint[:-1]

        raise TypeError((
            f"Missing option group decorator in '{ctx.command.name}' command for the following grouped options:\n"
            f"{options_error_hint}\n"))


class _OptGroup:
    """A helper class to manage creating groups and group options via decorators

    The class provides two decorator-methods: `group`/`__call__` and `option`.
    These decorators should be used for adding grouped options. The class have
    single global instance `optgroup` that should be used in most cases.

    The example of usage::

        ...
        @optgroup('Group 1', help='option group 1')
        @optgroup.option('--foo')
        @optgroup.option('--bar')
        @optgroup.group('Group 2', help='option group 2')
        @optgroup.option('--spam')
        ...
    """

    def __init__(self) -> None:
        self._decorating_state: ty.Dict[abc.Callable, ty.List[OptionStackItem]] = collections.defaultdict(list)
        self._not_attached_options: ty.Dict[abc.Callable, ty.List[click.Option]] = collections.defaultdict(list)

    def __call__(self, name: ty.Optional[str] = None, help: ty.Optional[str] = None,
                 cls: ty.Optional[ty.Type[OptionGroup]] = None, **attrs):
        return self.group(name, cls=cls, help=help, **attrs)

    def group(self, name: ty.Optional[str] = None, *,
              cls: ty.Optional[ty.Type[OptionGroup]] = None,
              help: ty.Optional[str] = None, **attrs):
        """The decorator creates a new group and collects its options

        Creates the option group and registers all grouped options
        which were added by `option` decorator.

        :param name: Group name or None for deault name
        :param cls: Option group class that should be inherited from `OptionGroup` class
        :param help: Group help or None for empty help
        :param attrs: Additional parameters of option group class
        """

        if not cls:
            cls = OptionGroup
        else:
            if not issubclass(cls, OptionGroup):
                raise TypeError("'cls' must be a subclass of 'OptionGroup' class.")

        def decorator(func):
            callback, params = get_callback_and_params(func)

            if callback not in self._decorating_state:
                with_name = f' "{name}"' if name else ''
                warnings.warn(
                    f'The empty option group{with_name} was found. The group will not be added.',
                    UserWarning)
                return func

            option_stack = self._decorating_state.pop(callback)

            [params.remove(opt) for opt in self._not_attached_options.pop(callback)]
            self._check_mixing_decorators(callback, option_stack, self._filter_not_attached(params))

            attrs['help'] = help

            try:
                option_group = cls(name, **attrs)
            except TypeError as err:
                message = str(err).replace('__init__()', f"'{cls.__name__}' constructor")
                raise TypeError(message) from err

            for item in option_stack:
                func = option_group.option(*item.param_decls, **item.attrs)(func)

            return func

        return decorator

    def option(self, *param_decls, **attrs):
        """The decorator adds a new option to the group

        The decorator is lazy. It adds option decls and attrs.
        All options will be registered by `group` decorator.

        :param param_decls: option declaration tuple
        :param attrs: additional option attributes and parameters
        """

        def decorator(func):
            callback, params = get_callback_and_params(func)

            option_stack = self._decorating_state[callback]
            params = self._filter_not_attached(params)

            self._check_mixing_decorators(callback, option_stack, params)
            self._add_not_attached_option(func, param_decls)
            option_stack.append(OptionStackItem(param_decls, attrs, len(params)))

            return func

        return decorator

    def _add_not_attached_option(self, func, param_decls):
        click.option(
            get_fake_option_name(),
            option_decls=param_decls,
            all_not_attached_options=self._not_attached_options,
            cls=_NotAttachedOption
        )(func)

        callback, params = get_callback_and_params(func)
        self._not_attached_options[callback].append(params[-1])

    @staticmethod
    def _filter_not_attached(options):
        return [opt for opt in options if not isinstance(opt, _NotAttachedOption)]

    @staticmethod
    def _check_mixing_decorators(callback, options_stack, params):
        if options_stack:
            last_state = options_stack[-1]

            if len(params) > last_state.param_count:
                raise_mixing_decorators_error(params[-1], callback)


optgroup = _OptGroup()
"""Provides decorators for creating option groups and adding grouped options

Decorators:
    - `group` is used for creating an option group
    - `option` is used for adding options to a group

Example::

    @optgroup.group('Group 1', help='option group 1')
    @optgroup.option('--foo')
    @optgroup.option('--bar')
    @optgroup.group('Group 2', help='option group 2')
    @optgroup.option('--spam')
"""
