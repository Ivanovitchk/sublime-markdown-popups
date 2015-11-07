"""
Markdown popup.

A markdown tooltip for SublimeText.

TextMate theme to CSS.

https://manual.macromates.com/en/language_grammars#naming_conventions

foreground
background
comment
comment.line
comment.line.double-slash
comment.line.double-dash
comment.line.number-sign
comment.line.percentage
comment.line.character
comment.block
comment.block.documentation
constant
constant.numeric
constant.character
constant.language
constant.other
entity
entity.name
entity.other
invalid
invalid.illegal
invalid.deprecated
keyword
keyword.control
keyword.operator
keyword.other
markup
markup.underline
markup.underline.link
markup.bold
markup.heading
markup.italic
markup.list
markup.list.numbered
markup.list.unnumbered
markup.quote
markup.raw
markup.other
meta
storage
storage.type
storage.modifier
string
string.quoted
string.quoted.single
string.quoted.double
string.quoted.triple
string.quoted.other
string.unquoted
string.interpolated
string.regexp
string.other
support
support.function
support.class
support.type
support.constant
support.variable
support.other
variable.parameter
variable.language
variable.other
"""
import sublime
import markdown
import traceback
from plistlib import readPlistFromBytes
import os
import re
import time
from .rgba import RGBA
from collections import OrderedDict, namedtuple
import jinja2

DARK = 0
LIGHT = 1
DEFAULT_DARK_THEME = 'Packages/mdpopups/themes/dark.css'
DEFAULT_LIGHT_THEME = 'Packages/mdpopups/themes/light.css'


re_textmate_scopes = re.compile(
    r'''(?x)^
    comment
      (?:\.(?:line(?:\.(?:double-slash|double-dash|number-sign|percentage|character))?|block(?:\.documentation)?))?|
    constant
      (?:\.(?:numeric|character|langauge|other))?|
    entity
      (?:\.(?:name|other))?|
    invalid
      (?:\.(?:illegal|deprecated))?|
    keyword
      (?:\.(?:control|operator|other))?|
    markup
      (?:\.(?:underline(?:\.link)?|link|bold|heading|italic|list(?:\.(?:numbered|unnumbered))?|quote|raw|other))?|
    meta|
    storage
      (?:\.(?:storage|type|modifier))?|
    string
      (?:\.(?:quoted(?:\.(?:single|double|triple|other))?|unquoted|interpolated|regexp|other))?|
    support
      (?:\.(?:function|class|type|constant|variable|other))?|
    variable
      (?:\.(?:parameter|language|other))?$
    '''
)

re_strip_xml_comments = re.compile(br"^[\r\n\s]*<!--[\s\S]*?-->[\s\r\n]*|<!--[\s\S]*?-->")


class Scheme2CSS(object):
    """Determine color scheme colors and style for text in a Sublime view buffer."""

    def __init__(self, scheme_file):
        """Initialize."""
        self.color_scheme = os.path.normpath(scheme_file)
        # self.scheme_file = os.path.basename(self.color_scheme)
        self.plist_file = readPlistFromBytes(
            re.sub(
                br"^[\r\n\s]*<!--[\s\S]*?-->[\s\r\n]*|<!--[\s\S]*?-->", b'',
                sublime.load_binary_resource(_sublime_format_path(scheme_file))
            )
        )
        self.text = ''
        self.colors = OrderedDict()
        self.scheme_file = scheme_file
        self.gen_css()

    def parse_scheme(self):
        """Parse the color scheme."""

        color_settings = self.plist_file["settings"][0]["settings"]

        # Get general theme colors from color scheme file
        self.bground = self.strip_color(color_settings.get("background", '#FFFFFF'), simple_strip=True)
        rgba = RGBA(self.bground)
        self.lums = rgba.luminance()
        self.is_dark = self.lums <= 127
        if self.is_dark:
            rgba.brightness(1.1)
        else:
            rgba.brightness(0.9)
        self.html_border = rgba.get_rgb()
        self.fground = self.strip_color(color_settings.get("foreground", '#000000'))

        # Create scope color mapping from color scheme file
        colors = OrderedDict()
        for item in self.plist_file["settings"]:
            name = item.get('name', None)
            scope = item.get('scope', None)
            color = None
            style = []
            if 'settings' in item:
                color = item['settings'].get('foreground', None)
                bgcolor = item['settings'].get('background', None)
                if 'fontStyle' in item['settings']:
                    for s in item['settings']['fontStyle'].split(' '):
                        if s == "bold" or s == "italic":  # or s == "underline":
                            style.append(s)

            if scope is not None and name is not None and (color is not None or bgcolor is not None):
                fg = self.strip_color(color)
                bg = self.strip_color(bgcolor)
                colors[scope] = {
                    "color": fg,
                    "bgcolor": bg,
                    "style": style
                }
        return colors

    def strip_color(self, color, simple_strip=False):
        """
        Strip transparency from the color value.

        Transparency can be stripped in one of two ways:
            - Simply mask off the alpha channel.
            - Apply the alpha channel to the color essential getting the color seen by the eye.
        """

        if color is None or color.strip() == "":
            return None

        rgba = RGBA(color.replace(" ", ""))
        if not simple_strip:
            rgba.apply_alpha(self.bground if self.bground != "" else "#FFFFFF")

        return rgba.get_rgb()

    def gen_css(self):
        """Get CSS."""

        colors = self.parse_scheme()
        self.colors = OrderedDict()
        self.colors['html'] = OrderedDict([('background-color', 'background-color: %s; ' % self.html_border)])
        self.colors['html']['all'] = self.colors['html']['background-color']
        self.colors['.foreground'] = OrderedDict([('color', 'color: %s; ' % self.fground)])
        self.colors['.foreground']['all'] = self.colors['.foreground']['color']
        self.colors['.background'] = OrderedDict([('background-color', 'background-color: %s; ' % self.bground)])
        self.colors['.background']['all'] = self.colors['.background']['background-color']

        for k, v in colors.items():
            for scope in [scope.strip() for scope in k.split(',')]:
                if ' ' in scope:
                    # Ignore complex scopes like:
                    #    "myscope.that.is way.to.complex" or "myscope.that.is -way.to.complex"
                    continue

                if re_textmate_scopes.match(scope):
                    key_scope = '.' + scope
                    self.colors[key_scope] = OrderedDict()
                    all_css = ''
                    if v['color']:
                        value = 'color: %s; ' % v['color']
                        self.colors[key_scope]['color'] = value
                        all_css += value
                    if v['bgcolor']:
                        value = 'background-color: %s; ' % v['bgcolor']
                        self.colors[key_scope]['background-color'] = value
                        all_css += value
                    if 'italic' in v['style']:
                        value = 'font-style: %s; ' % 'italic'
                        self.colors[key_scope]['font-style'] = value
                        all_css += value
                    if 'bold' in v['style']:
                        value = 'font-weight: %s; ' % 'bold'
                        self.colors[key_scope]['font-weight'] = value
                        all_css += value
                    self.colors[key_scope]['all'] = all_css

        text = []
        for k, v in self.colors.items():
            print(k)
            print(v)
            text.append('%s { %s}' % (k, v['all']))
        self.text = '\n'.join(text)

        # Create Jinja template
        self.env = jinja2.Environment()

    def apply_template(self, css):
        """Apply template to css."""

        return self.env.from_string(css).render(css=self.colors)

    def get_css(self):
        """Get css."""

        return self.text


class PopupTheme (namedtuple('PopupTheme', ['css', 'fg', 'bg', 'brightness'], verbose=False)):
    """Theme object containing the clean css, base colors, and brightness."""

    def is_light(self):
        """Check if theme is light."""

        return self.brightness == LIGHT

    def is_dark(self):
        """Check if theme is dark."""

        return self.brightness == DARK


def _log(msg):
    """Log."""

    print('MarkdownPopup: %s' % msg)


def _get_setting(name, default=None):
    """Get the Sublime setting."""

    return sublime.load_settings('Preferences.sublime-settings').get(name, default)


def _can_show(view):
    """
    Check if popup can be shown.

    I have seen Sublime can sometimes crash if trying
    to do a popup off screen.  Normally it should just not show,
    but sometimes it can crash.  We will check if popup
    can/should be attempted.
    """

    can_show = True
    sel = view.sel()
    if len(sel) >= 1:
        region = view.visible_region()
        if region.begin() > sel[0].b or region.end() < sel[0].b:
            can_show = False
    else:
        can_show = False

    return can_show

##############################
# Theme/Scheme cache management
##############################
_css_cache = OrderedDict()
_lum_cache = OrderedDict()
_scheme_cache = OrderedDict()


def _clear_cache():
    """Clear the css cache."""

    global _css_cache
    global _lum_cache
    global _scheme_cache
    _css_cache = OrderedDict()
    _lum_cache = OrderedDict()
    _scheme_cache = OrderedDict()

##############################
# Scheme Brightness Detection
##############################
LUM_MIDPOINT = 127


def _sublime_format_path(pth):
    """Format the path for sublime."""

    m = re.match(r"^([A-Za-z]{1}):(?:/|\\)(.*)", pth)
    if sublime.platform() == "windows" and m is not None:
        pth = m.group(1) + "/" + m.group(2)
    return pth.replace("\\", "/")


def _get_scheme_css(view, css):
    """Get css from scheme."""
    scheme = view.settings().get('color_scheme')
    obj = None
    if scheme is not None:
        if scheme in _scheme_cache:
            obj, t = _scheme_cache[scheme]
            delta_time = _get_setting('mdpopups_cache_refresh_time', 30)
            if not isinstance(delta_time, int) or delta_time <= 0:
                delta_time = 30
            if time.time() - t >= (delta_time * 60):
                obj = None
        if obj is None:
            try:
                obj = Scheme2CSS(scheme)
                limit = _get_setting('mdpopups_cache_limit', 10)
                if limit is None or not isinstance(limit, int) or limit <= 0:
                    limit = 10
                while len(_scheme_cache) >= limit:
                    _scheme_cache.popitem(last=True)
                _scheme_cache[scheme] = (obj, time.time())
            except Exception:
                print(traceback.format_exc())
                pass
    try:
        return obj.apply_template(DEFAULT_CSS) + obj.get_css() + obj.apply_template(css) if obj is not None else ''
    except Exception:
        print(traceback.format_exc())
        return ''


# def _scheme_lums(scheme_file):
#     """Get the scheme lumincance."""
#     color_scheme = os.path.normpath(scheme_file)
#     scheme_file = os.path.basename(color_scheme)
#     plist_file = readPlistFromBytes(
#         re.sub(
#             br"^[\r\n\s]*<!--[\s\S]*?-->[\s\r\n]*|<!--[\s\S]*?-->", b'',
#             sublime.load_binary_resource(_sublime_format_path(color_scheme))
#         )
#     )

#     color_settings = plist_file["settings"][0]["settings"]
#     lum = _RGBA(color_settings.get("background", '#FFFFFF'))
#     lum.apply_alpha('#FFFFFF')

#     print(Scheme2CSS(color_scheme).get_css())
#     return lum.get_luminance()


# def _get_scheme_lum(view):
#     """Get scheme lum."""

#     lum = None
#     scheme = view.settings().get('color_scheme')
#     if scheme is not None:
#         if scheme in _lum_cache:
#             lum, t = _lum_cache[scheme]
#             delta_time = _get_setting('mdpopups_cache_refresh_time', 30)
#             if not isinstance(delta_time, int) or delta_time <= 0:
#                 delta_time = 30
#             if time.time() - t >= (delta_time * 60):
#                 lum = None
#         if lum is None:
#             try:
#                 lum = _scheme_lums(scheme)
#                 limit = _get_setting('mdpopups_cache_limit', 10)
#                 if limit is None or not isinstance(limit, int) or limit <= 0:
#                     limit = 10
#                 while len(_lum_cache) >= limit:
#                     _lum_cache.popitem(last=True)
#                 _lum_cache[scheme] = (lum, time.time())
#             except Exception:
#                 pass
#     return lum if lum is not None else 255


def _get_theme_by_lums(lums):
    """Get theme based on lums."""

    if lums <= LUM_MIDPOINT:
        theme = _get_setting('mdpopups_theme_dark', DEFAULT_DARK_THEME)
        css_content, base_colors = _get_css(theme)
        if css_content is None:
            css_content, base_colors = _get_css(DEFAULT_DARK_THEME)
    else:
        theme = _get_setting('mdpopups_theme_light', DEFAULT_LIGHT_THEME)
        css_content, base_colors = _get_css(theme)
        if css_content is None:
            css_content, base_colors = _get_css(DEFAULT_LIGHT_THEME)
    return css_content, base_colors


##############################
# Scheme to theme mapping
##############################
def _get_theme_by_scheme_map(view):
    """Get mapped scheme if available."""

    css = None
    base_colors = None
    theme_map = _get_setting('mdpopups_theme_map', {})

    if theme_map:
        scheme = view.settings().get('color_scheme')
        if scheme is not None and scheme in theme_map:
            css, base_colors = _get_css(theme_map[scheme])
    return css, base_colors


##############################
# Markdown parsing
##############################
class _MdWrapper(markdown.Markdown):
    """
    Wrapper around Python Markdown's class.

    This allows us to gracefully continue when a module doesn't load.
    """

    Meta = {}

    def __init__(self, *args, **kwargs):
        """Call original init."""

        super(_MdWrapper, self).__init__(*args, **kwargs)

    def registerExtensions(self, extensions, configs):  # noqa
        """
        Register extensions with this instance of Markdown.

        Keyword arguments:

        * extensions: A list of extensions, which can either
           be strings or objects.  See the docstring on Markdown.
        * configs: A dictionary mapping module names to config options.

        """

        from markdown import util
        from markdown.extensions import Extension

        for ext in extensions:
            try:
                if isinstance(ext, util.string_type):
                    ext = self.build_extension(ext, configs.get(ext, {}))
                if isinstance(ext, Extension):
                    ext.extendMarkdown(self, globals())
                elif ext is not None:
                    raise TypeError(
                        'Extension "%s.%s" must be of type: "markdown.Extension"'
                        % (ext.__class__.__module__, ext.__class__.__name__)
                    )
            except Exception:
                # We want to gracefully continue even if an extension fails.
                _log(str(traceback.format_exc()))

        return self


def _get_theme(view, css=None):
    """Get the theme."""

    return _get_scheme_css(view, css)
    # css_content = css
    # if css_content is None:
    #     css_content, base_colors = _get_theme_by_scheme_map(view)

    #     if css_content is None:
    #         lums = _get_scheme_lum(view)
    #         css_content, base_colors = _get_theme_by_lums(lums)
    #     else:
    #         css_content, base_colors = _get_css(css)
    #         if css_content is None:
    #             lums = _get_scheme_lum(view)
    #             css_content, base_colors = _get_theme_by_lums(lums)
    # else:
    #     base_colors = _get_base_colors(css)
    #     try:
    #         css_content = _clean_css(css)
    #     except Exception:
    #         css_content = None
    # if css_content is None:
    #     css_content = ''
    # return DEFAULT_CSS + css


def _create_html(view, content, md=True, css=None, append_css=None, debug=False):
    """Create html from content."""

    if debug:
        _log('=====Content=====')
        _log(content)

    if append_css is not None and isinstance(append_css, str):
        try:
            append_css = _clean_css(append_css)
        except Exception:
            append_css = ''
    else:
        append_css = ''

    css_content = _get_theme(view, append_css)

    if debug:
        _log('=====CSS=====')
        _log(css_content)

    if md:
        content = md2html(content)

    if debug:
        _log('=====HTML OUTPUT=====')
        _log(content)

    html = "<style>%s</style>" % (css_content)
    html += '<div class="content background foreground">%s</div>' % content
    return html

##############################
# CSS parsing cache management
##############################
LINE_PRESERVE = re.compile(r"\r?\n", re.MULTILINE)
CSS_PATTERN = re.compile(
    r'''(?x)
        (?P<comments>
            /\*[^*]*\*+(?:[^/*][^*]*\*+)*/  # multi-line comments
        )
      | (?P<code>
            "(?:\\.|[^"\\])*"               # double quotes
          | '(?:\\.|[^'\\])*'               # single quotes
          | .[^/"']*                        # everything else
        )
    ''',
    re.DOTALL
)


def _clean_css(text, preserve_lines=False):
    """Clean css."""

    def remove_comments(group, preserve_lines=False):
        """Remove comments."""

        return ''.join([x[0] for x in LINE_PRESERVE.findall(group)]) if preserve_lines else ''

    def evaluate(m, preserve_lines):
        """Search for comments."""

        g = m.groupdict()
        return g["code"] if g["code"] is not None else remove_comments(g["comments"], preserve_lines)

    return ''.join(map(lambda m: evaluate(m, preserve_lines), CSS_PATTERN.finditer(text.replace('\r', ''))))


def _get_css(css_file):
    """
    Get css file.

    Strip out comments and carriage returns.  Return the css content and base_colors.
    """
    css = None
    base_colors = None
    if css_file in _css_cache:
        css, base_colors, t = _css_cache[css_file]

        delta_time = _get_setting('mdpopups_cache_refresh_time', 30)
        if delta_time is None or not isinstance(delta_time, int) or delta_time <= 0:
            delta_time = 30
        if time.time() - t >= (delta_time * 60):
            css = None
            base_colors = None
    if css is None:
        try:
            css_raw = sublime.load_resource(css_file)
            base_colors = _get_base_colors(css_raw)
            css = _clean_css(css_raw)
            limit = _get_setting('mdpopups_cache_limit', 10)
            if limit is None or not isinstance(limit, int) or limit <= 0:
                limit = 10
            while len(_css_cache) >= limit:
                _css_cache.popitem(last=True)
            _css_cache[css_file] = (css, base_colors, time.time())
        except Exception as e:
            print(e)
            pass
    return css, (base_colors if base_colors is not None else ('#000000', '#FFFFFF'))


def _get_base_colors(css):
    """
    Get background and foreground color from theme.

    Themes should define as the first line the background color so
    that theme brightness can be determined.
    """

    # re.compile(
    #     r'''(?x)
    #     ^\s*\.(
    #         st-(?:foreground|background|comment|constant|string|keyword|entity|storage|variable|invalid)|
    #         neutral|positive|negative|mark-neutral|mark-positive|mark-negative|
    #         admonition(?:\.(?:hint|tip|danger|error|important|attention|caution|warning|note))?
    #     )\s*(?=,|\{)
    #     ''',
    #     re.MULTILINE
    # )

    bg = '#ffffff'
    fg = '#000000'
    if css and isinstance(css, str):
        m = re.match(
            r'''(?x)
            /\*[ \t]*mdpopups:[ \t]*
            fg[ \t]*=[ \t]*(\#(?:(?:[A-Fa-f\d]{6})|(?:[A-Fa-f\d]{3})))
            (?:[ \t]*,[ \t]*bg[ \t]*=[ \t]*(\#(?:(?:[A-Fa-f\d]{6})|(?:[A-Fa-f\d]{3}))))? |
            bg[ \t]*=[ \t]*(\#(?:(?:[A-Fa-f\d]{6})|(?:[A-Fa-f\d]{3})))
            (?:[ \t]*,[ \t]*fg[ \t]*=[ \t]*(\#(?:(?:[A-Fa-f\d]{6})|(?:[A-Fa-f\d]{3}))))?
            ''',
            css[0:256]
        )
        if m:
            if m.group(1):
                fg = m.group(1)
                if m.group(2):
                    bg = m.group(2)
            else:
                bg = m.group(3)
                if m.group(4):
                    fg = m.group(4)
    return fg, bg


##############################
# Public functions
##############################
DEFAULT_CSS = _clean_css(
    '''
html { background-color: black; } /* Html fake border color */
/* Defines the general look of the font and provides a little margin. */
body {
    color: white;
    margin: 1px;
    font-size: 1em;
}
/* Headers */
h1 { font-size: 1.5em; }
h2, h3, h4, h5, h6 { font-size: 1.2em; }
/* Blockquote support. */
blockquote {
    padding: 0.5em;
    display: block;
    font-style: italic;
}
/* Horizontal rule support. */
hr {
    display: block;
    padding: 1px;
    margin: 1em 3em;
}
/* Description list support */
dl {
    display: block;
    margin-top: 1em;
    margin-bottom: 1em;
    margin-left: 0;
    margin-right: 0;
}
dt { display: block; font-style: italic; font-weight: bold; }
dd { display: block; margin-left: 2em; }
/* Link */
a { color: blue }
div.content { padding: 0.5em; } /* Content wrapper div. */
/*Style with current theme.*/
h1, h2, h3, h4, h5, h6 { {{ css['.string']['all'] }} }
a { {{css['.support.function']['all']}} }
    '''
)


# def get_theme(view, css=None, from_file=False):
#     """
#     Get the current theme.

#     Returns the theme, base_colors, and whether the background is DARK or LIGHT.
#     """

#     css, base_colors = _get_css(from_file) if from_file else _get_theme(view, css)
#     lum = _Luminance(base_colors[1])
#     lum.apply_alpha('#FFFFFF')
#     brightness = lum.get_luminance()
#     if brightness is None:
#         brightness = 255
#     bg_lum = DARK if brightness <= LUM_MIDPOINT else LIGHT
#     ptheme = PopupTheme(css, base_colors[0], base_colors[1], bg_lum)
#     return ptheme


def md2html(markup):
    """Convert Markdown to HTML."""

    extensions = [
        "markdown.extensions.attr_list",
        "markdown.extensions.codehilite",
        "mdpopups.mdx.superfences",
        "mdpopups.mdx.betterem",
        "mdpopups.mdx.magiclink",
        "mdpopups.mdx.inlinehilite",
        "markdown.extensions.nl2br",
        "markdown.extensions.admonition",
        "markdown.extensions.def_list"
    ]

    configs = {
        "mdpopups.mdx.inlinehilite": {
            "style_plain_text": True,
            "css_class": "inlinehilite",
            "use_codehilite_settings": False,
            "guess_lang": False
        },
        "markdown.extensions.codehilite": {
            "guess_lang": False
        },
        "mdpopups.mdx.superfences": {
            "uml_flow": False,
            "uml_sequence": False
        }
    }

    return _MdWrapper(
        extensions=extensions,
        extension_configs=configs
    ).convert(markup).replace('&quot;', '"').replace('\n', '')


def clear_cache():
    """Clear cache."""

    _clear_cache()


def hide_popup(view):
    """Hide the popup."""

    view.hide_popup()


def update_popup(view, content, md=True, css=None, append_css=None):
    """Update the popup."""

    debug = _get_setting('mdpopups_debug')
    disabled = _get_setting('mdpopups_disable', False)
    if disabled:
        if debug:
            _log('Popups disabled')
        return

    if not _can_show(view):
        return

    html = _create_html(view, content, md, css, append_css, debug)

    view.update_popup(html)


def show_popup(
    view, content, md=True, css=None, append_css=None,
    flags=0, location=-1, max_width=320, max_height=240,
    on_navigate=None, on_hide=None
):
    """Parse the color scheme if needed and show the styled pop-up."""

    debug = _get_setting('mdpopups_debug')
    disabled = _get_setting('mdpopups_disable', False)
    if disabled:
        if debug:
            _log('Popups disabled')
        return

    if not _can_show(view):
        return

    html = _create_html(view, content, md, css, append_css, debug)

    view.show_popup(
        html, flags=flags, location=location, max_width=max_width,
        max_height=max_height, on_navigate=on_navigate, on_hide=on_hide
    )
