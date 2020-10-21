import collections
import itertools
from krpc.types import \
    ValueType, ClassType, EnumerationType, MessageType, \
    TupleType, ListType, SetType, DictionaryType
from krpc.schema.KRPC_pb2 import Type
from krpc.utils import snake_case
from .generator import Generator
from .docparser import DocParser
from ..lang.python import PythonLanguage
from ..utils import lower_camel_case, upper_camel_case, as_type


class PythonGenerator(Generator):

    language = PythonLanguage()

    def parse_type_specification(self, typ):
        if typ is None:
            return 'None'
        if isinstance(typ, ValueType):
            return self.language.parse_type(typ)
        elif isinstance(typ, MessageType):
            return self.language.parse_type(typ)
        elif isinstance(typ, ClassType):
            return self.language.parse_type(typ)
        elif isinstance(typ, EnumerationType):
            return self.language.parse_type(typ)
        elif isinstance(typ, TupleType):
            return 'Tuple[%s]' % \
                ','.join(self.parse_type_specification(t)
                         for t in typ.value_types)
        elif isinstance(typ, ListType):
            return 'List[%s]' % \
                self.parse_type_specification(typ.value_type)
        elif isinstance(typ, SetType):
            return 'Set[%s]' % \
                self.parse_type_specification(typ.value_type)
        elif isinstance(typ, DictionaryType):
            return 'Dict[%s, %s]' % \
                (self.parse_type_specification(typ.key_type),
                 self.parse_type_specification(typ.value_type))
        raise RuntimeError('Unknown type ' + typ)

    def parse_context(self, context):
        # Expand service properties into get and set methods
        properties = collections.OrderedDict()
        for name, info in context['properties'].items():
            if name not in properties:
                properties[name] = {}

            if info['getter']:
                properties[name]['getter'] = {
                    'procedure': info['getter']['procedure'],
                    'remote_name': info['getter']['remote_name'],
                    'parameters': [],
                    'return_type': info['type'],
                    'documentation': info['documentation']
                }
            if info['setter']:
                properties[name]['setter'] = {
                    'procedure': info['setter']['procedure'],
                    'remote_name': info['setter']['remote_name'],
                    'parameters': self.generate_context_parameters(
                        info['setter']['procedure']),
                    'return_type': 'None',
                    'documentation': info['documentation']
                }
        context['properties'] = properties

        # Expand class properties into get and set methods
        for class_name, class_info in context['classes'].items():
            class_properties = collections.OrderedDict()
            for name, info in class_info['properties'].items():
                if  name not in class_properties:
                    class_properties[name] = {}
                if info['getter']:
                    class_properties[name]['getter'] = {
                        'procedure': info['getter']['procedure'],
                        'remote_name': info['getter']['remote_name'],
                        'parameters': [],
                        'return_type': info['type'],
                        'documentation': info['documentation']
                    }
                if info['setter']:
                    class_properties[name]['setter'] = {
                        'procedure': info['setter']['procedure'],
                        'remote_name': info['setter']['remote_name'],
                        'parameters': [
                            self.generate_context_parameters(
                                info['setter']['procedure'])[1]],
                        'return_type': 'None',
                        'documentation': info['documentation']
                    }
            class_info['properties'] = class_properties

        # Find all service dependencies
        dependencies = set()
        procedures = \
            context['procedures'].values() + \
            [procedure \
                for property_accessors in context['properties'].values() \
                for getter_or_setter, procedure in property_accessors.items()] + \
            list(itertools.chain(
                *[class_info['static_methods'].values()
                  for class_info in context['classes'].values()]))
        for info in procedures:
            if 'return_type' in info['procedure']:
                return_type = info['procedure']['return_type']
                if 'service' in return_type and context['service_name'] != return_type['service']:
                    dependencies.add(return_type['service'])
            pos = 0
            for i, pinfo in enumerate(info['parameters']):
                param_type = info['procedure']['parameters'][i]['type']
                if 'service' in param_type and context['service_name'] != param_type['service']:
                    dependencies.add(param_type['service'])
                pos += 1

        for class_info in context['classes'].values():
            items = class_info['methods'].values() + \
                    [procedure \
                        for property_accessors in class_info['properties'].values()\
                        for getter_or_setter, procedure in property_accessors.items()]
            for info in items:
                if 'return_type' in info['procedure']:
                    return_type = info['procedure']['return_type']
                    if 'service' in return_type and context['service_name'] != return_type['service']:
                        dependencies.add(return_type['service'])
                pos = 0
                for i, pinfo in enumerate(info['parameters']):
                    param_type = info['procedure']['parameters'][i]['type']
                    if 'service' in param_type and context['service_name'] != param_type['service']:
                        dependencies.add(param_type['service'])
                    pos += 1
        context['dependencies'] = dependencies

        # Add type specifications to types
        procedures = \
            context['procedures'].values() + \
            [procedure \
                for property_accessors in context['properties'].values() \
                for getter_or_setter, procedure in property_accessors.items()] + \
            list(itertools.chain(
                *[class_info['static_methods'].values()
                  for class_info in context['classes'].values()]))
        for info in procedures:
            info['return_type'] = {
                'name': info['return_type'],
                'spec': self.parse_type_specification(
                    self.get_return_type(info['procedure']))
            }
            pos = 0
            for i, pinfo in enumerate(info['parameters']):
                param_type = as_type(
                    self.types, info['procedure']['parameters'][i]['type'])
                pinfo['type'] = {
                    'name': pinfo['type'],
                    'spec': self.parse_type_specification(param_type)
                }
                pos += 1

        for class_info in context['classes'].values():
            items = class_info['methods'].values() + \
                    [procedure \
                        for property_accessors in class_info['properties'].values()\
                        for getter_or_setter, procedure in property_accessors.items()]
            for info in items:
                info['return_type'] = {
                    'name': info['return_type'],
                    'spec': self.parse_type_specification(
                        self.get_return_type(info['procedure']))
                }
                pos = 0
                for i, pinfo in enumerate(info['parameters']):
                    param_type = as_type(
                        self.types,
                        info['procedure']['parameters'][i+1]['type'])
                    pinfo['type'] = {
                        'name': pinfo['type'],
                        'spec': self.parse_type_specification(param_type)
                    }
                    pos += 1

        return context

    @staticmethod
    def parse_documentation(documentation):
        documentation = PythonDocParser().parse(documentation)
        if documentation == '':
            return ''
        documentation = "\"\"\"" + documentation + "\"\"\""
        # content = content.replace('  <param', '<param')
        # content = content.replace('  <returns', '<returns')
        # content = content.replace('  <remarks', '<remarks')
        return documentation

class PythonDocParser(DocParser):
    def parse_summary(self, node):
        return self.parse_node(node).strip()

    def parse_remarks(self, node):
        return '\n\n'+self.parse_node(node).strip()

    def parse_param(self, node):
        return '\n:%s %s' % (snake_case(node.attrib['name']),
                                   self.parse_node(node).strip())

    def parse_returns(self, node):
        return '\n@return %s' % self.parse_node(node).strip()

    def parse_see(self, node):
        return self.parse_cref(node.attrib['cref'])

    @staticmethod
    def parse_paramref(node):
        return snake_case(node.attrib['name'])

    @staticmethod
    def parse_a(node):
        return node.text

    @staticmethod
    def parse_c(node):
        return '{@code %s}' % node.text

    @staticmethod
    def parse_math(node):
        return node.text

    def parse_list(self, node):
        content = ['<li>%s\n' % self.parse_node(item[0], indent=2)[2:].rstrip()
                   for item in node]
        return '<p><ul>'+'\n'+''.join(content)+'</ul></p>'

    @staticmethod
    def parse_cref(cref):
        if cref[0] == 'M':
            cref = cref[2:].split('.')
            member = lower_camel_case(cref[-1])
            del cref[-1]
            return '.'.join(cref)+'#'+member
        elif cref[0] == 'T':
            return cref[2:]
        else:
            raise RuntimeError('Unknown cref \'%s\'' % cref)