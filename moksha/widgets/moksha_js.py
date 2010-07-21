# This file is part of Moksha.
# Copyright (C) 2008-2010  Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from tw.api import JSLink
from tw.jquery import jquery_js

moksha_js = JSLink(modname=__name__,
        filename='static/moksha.js',
        javascript=[jquery_js])

moksha_extension_points_js = JSLink(modname="moksha",
        filename='public/javascript/moksha.extensions.js',
        javascript=[moksha_js])