# vim: ts=8:sts=8:sw=8:noexpandtab

# This file is part of python-markups module
# License: 3-clause BSD, see LICENSE file
# Copyright: (C) Dmitry Shachnev, 2012-2018

from __future__ import absolute_import

import importlib
import os
import ast
import re
import warnings
import markups.common as common
from markups.abstract import AbstractMarkup, ConvertedMarkup

MATHJAX_CONFIG = \
'''<script type="text/x-mathjax-config">
MathJax.Hub.Config({
  config: ["MMLorHTML.js"],
  jax: ["input/TeX", "input/AsciiMath", "output/HTML-CSS", "output/NativeMML"],
  extensions: ["MathMenu.js", "MathZoom.js"],
  TeX: {
    extensions: ["AMSmath.js", "AMSsymbols.js"],
    equationNumbers: {autoNumber: "AMS"}
  }
});
</script>
'''

extensions_re = re.compile(r'required.extensions: (.+)', flags=re.IGNORECASE)
extension_name_re = re.compile(r'[a-z0-9_.]+(?:\([^)]+\))?', flags=re.IGNORECASE)

_canonicalized_ext_names = {}

class MarkdownMarkup(AbstractMarkup):
	"""Markup class for Markdown language.
	Inherits :class:`~markups.abstract.AbstractMarkup`.

	:param extensions: list of extension names
	:type extensions: list
	"""
	name = 'Markdown'
	attributes = {
		common.LANGUAGE_HOME_PAGE: 'https://daringfireball.net/projects/markdown/',
		common.MODULE_HOME_PAGE: 'https://github.com/Python-Markdown/markdown',
		common.SYNTAX_DOCUMENTATION: 'https://daringfireball.net/projects/markdown/syntax'
	}

	file_extensions = ('.md', '.mkd', '.mkdn', '.mdwn', '.mdown', '.markdown')
	default_extension = '.mkd'

	@staticmethod
	def available():
		try:
			import markdown
		except ImportError:
			return False
		return (hasattr(markdown, '__version_info__') or  # underscored attribute means 3.x
		        hasattr(markdown, 'version_info') and markdown.version_info >= (2, 6))

	def _load_extensions_list_from_file(self, filename):
		try:
			extensions_file = open(filename)
		except IOError:
			return []
		else:
			extensions = [line.rstrip() for line in extensions_file
			              if not line.startswith('#')]
			extensions_file.close()
			return extensions

	def _get_global_extensions(self, filename):
		extensions = self._load_extensions_list_from_file(
			os.path.join(common.CONFIGURATION_DIR, 'markdown-extensions.txt'))
		local_directory = os.path.dirname(filename) if filename else ''
		extensions += self._load_extensions_list_from_file(
			os.path.join(local_directory, 'markdown-extensions.txt'))
		return extensions

	def _get_document_extensions(self, text):
		lines = text.splitlines()
		match = extensions_re.search(lines[0]) if lines else None
		if match:
			return extension_name_re.findall(match.group(1))
		return []

	def _canonicalize_extension_name(self, extension_name):
		prefixes = ('markdown.extensions.', '', 'mdx_')
		for prefix in prefixes:
			try:
				module = importlib.import_module(prefix + extension_name)
				if not hasattr(module, 'makeExtension'):
					continue
			except (ImportError, ValueError, TypeError):
				pass
			else:
				return prefix + extension_name

	def _split_extension_config(self, extension_name):
		"""Splits the configuration options from the extension name."""
		def _aux_(node):
			while not hasattr(node, 'id'):
				yield node.attr
				node = node.value
			yield node.id

		expression = ast.parse(extension_name).body[0].value
		
		solve_name = lambda exp: ".".join(reversed(list(_aux_(exp))))

		if not isinstance(expression, ast.Call):
			extension_name = solve_name(expression)
			return extension_name, {}

		extension_name = solve_name(expression.func)
		
		kwargs = {arg.arg: ast.literal_eval(arg.value) for arg in expression.keywords}

		return extension_name, kwargs


	def _apply_extensions(self):
		extensions = (self.requested_extensions +
			self.global_extensions + self.document_extensions)
		extension_names = {"markdown.extensions.extra", "mdx_math"}
		extension_configs = {}

		for extension in extensions:
			if extension == 'mathjax':
				mathjax_config = {"enable_dollar_delimiter": True}
				extension_configs["mdx_math"] = mathjax_config
			elif extension == 'remove_extra':
				if "markdown.extensions.extra" in extension_names:
					extension_names.remove("markdown.extensions.extra")
				if "mdx_math" in extension_names:
					extension_names.remove("mdx_math")
			else:
				name, config = self._split_extension_config(extension)
				if name in _canonicalized_ext_names:
					canonical_name = _canonicalized_ext_names[name]
				else:
					canonical_name = self._canonicalize_extension_name(name)
					if canonical_name is None:
						warnings.warn('Extension "%s" does not exist.' %
							extension, ImportWarning)
						continue
					_canonicalized_ext_names[name] = canonical_name
				extension_names.add(canonical_name)
				extension_configs[canonical_name] = config
		self.md = self.markdown.Markdown(extensions=list(extension_names),
		                                 extension_configs=extension_configs,
		                                 output_format='html5')
		self.extensions = extension_names
		self.extension_configs = extension_configs

	def __init__(self, filename=None, extensions=None):
		AbstractMarkup.__init__(self, filename)
		import markdown
		self.markdown = markdown
		self.requested_extensions = extensions or []
		if extensions is None:
			self.global_extensions = self._get_global_extensions(filename)
		else:
			self.global_extensions = []
		self.document_extensions = []
		self._apply_extensions()

	def convert(self, text):

		# Determine body
		self.md.reset()
		self.document_extensions = self._get_document_extensions(text)
		self._apply_extensions()
		body = self.md.convert(text) + '\n'

		# Determine title
		if hasattr(self.md, 'Meta') and 'title' in self.md.Meta:
			title = str.join(' ', self.md.Meta['title'])
		else:
			title = ''

		# Determine stylesheet
		css_class = None

		if 'markdown.extensions.codehilite' in self.extensions:
			config = self.extension_configs.get('markdown.extensions.codehilite', {})
			css_class = config.get('css_class', 'codehilite')
			stylesheet = common.get_pygments_stylesheet('.%s' % css_class)
		elif 'pymdownx.highlight' in self.extensions:
			config = self.extension_configs.get('pymdownx.highlight', {})
			css_class = config.get('css_class', 'highlight')
			stylesheet = common.get_pygments_stylesheet('.%s' % css_class)
		else:
			stylesheet = ''

		return ConvertedMarkdown(body, title, stylesheet)

class ConvertedMarkdown(ConvertedMarkup):

	def get_javascript(self, webenv=False):
		if '<script type="math/' in self.body:
			javascript = (MATHJAX_CONFIG + '<script type="text/javascript" src="'
		                                     + common.get_mathjax_url(webenv) + '"></script>')
		else:
			javascript = ''

		return javascript
