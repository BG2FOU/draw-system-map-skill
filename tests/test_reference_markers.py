"""Compare transfer silhouettes with the user's completed map reference geometry."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from draw_map import marker

COLORS=['#E27326','#52AB43','#2EC6D6','#E71419','#BA28B9','#0099CC']

class ReferenceMarkerTests(unittest.TestCase):
    def assert_reference_pixels(self,count,arc,head):
        try:
            import gi
            gi.require_version('Rsvg','2.0')
            from gi.repository import Rsvg
        except (ImportError,ValueError):
            self.skipTest('Reference silhouette pixels require librsvg')
        def pixels(fragment):
            svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><rect width="300" height="300" fill="#dddddd"/><g transform="translate(150 150) scale(5)">{fragment}</g></svg>'
            return bytes(Rsvg.Handle.new_from_data(svg.encode()).get_pixbuf().get_pixels())
        # These paths are the reference artwork, independent of the renderer's
        # coordinate construction. Keep the same silhouette when scaling it.
        for radius in [12.5,16,17.5]:
            reference='<circle r="17.5" fill="#ffffff"/>'
            for i,color in enumerate(COLORS[:count]):
                reference+=(f'<g transform="rotate({i*360/count})"><path d="{arc}" stroke="{color}" stroke-width="4.5" fill="none" stroke-linecap="round"/><path d="{head}" fill="{color}"/></g>')
            expected=pixels(f'<g transform="scale({radius/12.5})">{reference}</g>')
            actual=pixels(marker(COLORS[:count],radius,False,'arrows','#ffffff','#858b91'))
            self.assertEqual(actual,expected)

    def test_two_line_silhouette_matches_reference_half_arrows(self):
        self.assert_reference_pixels(2,'M10.82532 -6.25 A12.5 12.5 0 0 0 -10.82532 -6.25',
                                    'M-14.54923 -8.4 L-14.82532 .6782 L-7.10141 -4.1 Z')

    def test_three_line_silhouette_matches_reference_thirds(self):
        self.assert_reference_pixels(3,'M10.82532 -6.25 A12.5 12.5 0 0 0 -6.25 -10.82532',
                                    'M-3 -16 L-11 -9 L-1 -7 Z')

    def test_many_lines_keep_each_color_and_reserved_markers_stay_gray(self):
        for count in [4,6,8]:
            palette=(COLORS*2)[:count]
            for reserved in [False,True]:
                root=ET.fromstring('<g>'+marker(palette,16,reserved,'arrows','#ffffff','#858b91')+'</g>')
                arrows=root.findall('path[@class="transfer-arrow"]')
                heads=root.findall('path[@class="transfer-head"]')
                self.assertEqual(len(arrows),count)
                self.assertEqual(len(heads),count)
                expected=['#858b91']*count if reserved else palette
                self.assertEqual([p.attrib['stroke'] for p in arrows],expected)
                self.assertEqual([p.attrib['fill'] for p in heads],expected)
                self.assertTrue(all(float(p.attrib['stroke-width'])>0 for p in arrows))

if __name__=='__main__':unittest.main()
