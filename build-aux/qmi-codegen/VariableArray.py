#!/usr/bin/env python
# -*- Mode: python; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*-
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License along
# with this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright (C) 2012 Lanedo GmbH
#

import string
import utils
from Variable import Variable
import VariableFactory

"""
Variable type for Arrays ('array' format)
"""
class VariableArray(Variable):

    """
    Constructor
    """
    def __init__(self, dictionary, array_element_type):

        # Call the parent constructor
        Variable.__init__(self, dictionary)

        self.private_format  = 'GArray *'
        self.public_format = self.private_format

        # The array and its contents need to get disposed
        self.needs_dispose = True

        # Load variable type of this array
        if 'name' in dictionary['array-element']:
            self.array_element = VariableFactory.create_variable(dictionary['array-element'], array_element_type + ' ' + dictionary['array-element']['name'])
        else:
            self.array_element = VariableFactory.create_variable(dictionary['array-element'], '')


    """
    Emit the type for the array element
    """
    def emit_types(self, f):
        self.array_element.emit_types(f)

    """
    Emits the code to clear the element of the array
    """
    def emit_helper_methods(self, hfile, cfile):
        # No need for the clear func if no need to dispose the contents
        if self.array_element.needs_dispose == False:
            return

        translations = { 'element_format'   : self.array_element.public_format,
                         'underscore'       : utils.build_underscore_name_from_camelcase(self.array_element.public_format),
                         'dispose_contents' : self.array_element.build_dispose('    ', '(*p)') }

        template = (
            '\n'
            'static void\n'
            '${underscore}_clear (${element_format} *p)\n'
            '{\n'
            '$dispose_contents'
            '}\n')
        cfile.write(string.Template(template).substitute(translations))


    """
    Reading an array from the raw byte buffer is just about providing a loop to
    read every array element one by one.
    """
    def emit_buffer_read(self, f, line_prefix, variable_name, buffer_name, buffer_len):
        translations = { 'lp'             : line_prefix,
                         'private_format' : self.private_format,
                         'public_array_element_format' : self.array_element.public_format,
                         'underscore'     : utils.build_underscore_name_from_camelcase(self.array_element.public_format),
                         'variable_name'  : variable_name,
                         'buffer_name'    : buffer_name,
                         'buffer_len'     : buffer_len }

        template = (
            '${lp}{\n'
            '${lp}    guint i;\n'
            '${lp}    guint8 n_items;\n'
            '\n'
            '${lp}    /* Read number of items in the array */\n'
            '${lp}    n_items = ${buffer_name}[0];\n'
            '${lp}    ${buffer_name}++;\n'
            '${lp}    ${buffer_len}--;\n'
            '\n'
            '${lp}    ${variable_name} = g_array_sized_new (\n'
            '${lp}        FALSE,\n'
            '${lp}        FALSE,\n'
            '${lp}        sizeof (${public_array_element_format}),\n'
            '${lp}        n_items);\n'
            '\n')

        if self.array_element.needs_dispose == True:
            template += (
                '${lp}    g_array_set_clear_func (${variable_name},\n'
                '${lp}                            (GDestroyNotify)${underscore}_clear);\n'
                '\n')

        template += (
            '${lp}    for (i = 0; i < n_items; i++) {\n'
            '${lp}        ${public_array_element_format} aux;\n'
            '\n')
        f.write(string.Template(template).substitute(translations))

        self.array_element.emit_buffer_read(f, line_prefix + '        ', 'aux', buffer_name, buffer_len)

        template = (
            '${lp}        g_array_insert_val (${variable_name}, i, aux);\n'
            '${lp}    }\n'
            '${lp}}\n')
        f.write(string.Template(template).substitute(translations))


    """
    Writing an array to the raw byte buffer is just about providing a loop to
    write every array element one by one.
    """
    def emit_buffer_write(self, f, line_prefix, variable_name, buffer_name, buffer_len):
        raise RuntimeError('Not implemented yet')


    """
    The array will be printed as a list of fields enclosed between curly
    brackets
    """
    def emit_get_printable(self, f, line_prefix, printable, buffer_name, buffer_len):
        translations = { 'lp'          : line_prefix,
                         'printable'   : printable,
                         'buffer_name' : buffer_name,
                         'buffer_len'  : buffer_len }

        template = (
            '${lp}{\n'
            '${lp}    guint i;\n'
            '${lp}    guint8 n_items;\n'
            '\n'
            '${lp}    /* Read number of items in the array */\n'
            '${lp}    n_items = ${buffer_name}[0];\n'
            '${lp}    ${buffer_name}++;\n'
            '${lp}    ${buffer_len}--;\n'
            '\n'
            '${lp}    g_string_append (${printable}, "{");\n'
            '\n'
            '${lp}    for (i = 0; i < n_items; i++) {\n'
            '${lp}        g_string_append_printf (${printable}, " [%u] = \'", i);\n')
        f.write(string.Template(template).substitute(translations))

        self.array_element.emit_get_printable(f, line_prefix + '        ', printable, buffer_name, buffer_len);

        template = (
            '${lp}        g_string_append (${printable}, " \'");\n'
            '${lp}    }\n'
            '\n'
            '${lp}    g_string_append (${printable}, "}");\n'
            '${lp}}')
        f.write(string.Template(template).substitute(translations))


    """
    Variable declaration
    """
    def build_variable_declaration(self, line_prefix, variable_name):
        translations = { 'lp'   : line_prefix,
                         'name' : variable_name }

        template = (
            '${lp}GArray *${name};\n')
        return string.Template(template).substitute(translations)


    """
    Getter for the array type
    """
    def build_getter_declaration(self, line_prefix, variable_name):
        translations = { 'lp'   : line_prefix,
                         'name' : variable_name }

        template = (
            '${lp}GArray **${name},\n')
        return string.Template(template).substitute(translations)


    """
    Documentation for the getter
    """
    def build_getter_documentation(self, line_prefix, variable_name):
        translations = { 'lp'                          : line_prefix,
                         'public_array_element_format' : self.array_element.public_format,
                         'name'                        : variable_name }

        template = (
            '${lp}@${name}: a placeholder for the output #GArray of #${public_array_element_format} elements, or #NULL if not required. Do not free it, it is owned by @self.\n')
        return string.Template(template).substitute(translations)


    """
    Builds the array getter implementation
    """
    def build_getter_implementation(self, line_prefix, variable_name_from, variable_name_to, to_is_reference):
        translations = { 'lp'   : line_prefix,
                         'from' : variable_name_from,
                         'to'   : variable_name_to }

        if to_is_reference:
            template = (
                '${lp}if (${to})\n'
                '${lp}    *${to} = ${from};\n')
            return string.Template(template).substitute(translations)
        else:
            template = (
                '${lp}${to} = ${from};\n')
            return string.Template(template).substitute(translations)


    """
    Setter for the array type
    """
    def build_setter_declaration(self, line_prefix, variable_name):
        translations = { 'lp'   : line_prefix,
                         'name' : variable_name }

        template = (
            '${lp}GArray *${name},\n')
        return string.Template(template).substitute(translations)


    """
    Documentation for the setter
    """
    def build_setter_documentation(self, line_prefix, variable_name):
        translations = { 'lp'                          : line_prefix,
                         'public_array_element_format' : self.array_element.public_format,
                         'name'                        : variable_name }

        template = (
            '${lp}@${name}: a #GArray of #${public_array_element_format} elements. A new reference to @{name} will be taken.\n')
        return string.Template(template).substitute(translations)


    """
    Builds the array setter implementation
    """
    def build_setter_implementation(self, line_prefix, variable_name_from, variable_name_to):
        translations = { 'lp'   : line_prefix,
                         'from' : variable_name_from,
                         'to'   : variable_name_to }

        template = (
            '${lp}if (${to})\n'
            '${lp}    g_array_unref (${to});\n'
            '${lp}${to} = g_array_ref (${from});\n')
        return string.Template(template).substitute(translations)


    """
    Dispose the array just with an unref
    """
    def build_dispose(self, line_prefix, variable_name):
        translations = { 'lp'            : line_prefix,
                         'variable_name' : variable_name }

        template = (
            '${lp}g_array_unref (${variable_name});\n')
        return string.Template(template).substitute(translations)
