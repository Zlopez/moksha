import os
import moksha.common.config
from nose.tools import eq_, raises


def load_config(filename='/test_config.ini'):
    p = moksha.common.config.EnvironmentConfigParser()
    filename = '/'.join(__file__.split('/')[:-1] + [filename])
    p.read(filenames=[filename])
    return p


def test_config():
    expected = 'test_value 123'
    os.environ['test_variable'] = expected
    p = load_config()
    actual = p.get('test', 'test')
    eq_(actual, expected)


@raises(ValueError)
def test_invalid_config():
    expected = 'test_value 123'
    os.environ['test_variable'] = expected
    p = load_config('/test_invalid_config.ini')
    p.get('test', 'test')
