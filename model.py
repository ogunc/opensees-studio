"""OpenSees model exported by OpenSees Studio 0.0.3.

Project: Untitled
Units:   SI (m, N, kg, s, Pa)
Model:   4 nodes, 5 elements, ndm=3, ndf=6
Case:    #1 Static 'Static'

This is plain OpenSeesPy: ``python model.py`` builds the model and runs the case above.
It is the same command sequence the application gives the solver, with the
result extraction removed.
"""

import openseespy.opensees as ops

ops.wipe()
ops.model('basic', '-ndm', 3, '-ndf', 6)
ops.node(1, 0.0, 0.0, 0.0)
ops.node(2, 2.0, 0.0, 2.0)
ops.node(3, 4.0, 0.0, 0.0)
ops.node(4, 2.0, 2.0, 0.0)
ops.fix(1, 1, 1, 1, 0, 0, 0)
ops.fix(2, 1, 1, 1, 0, 0, 0)
ops.fix(3, 1, 1, 1, 0, 0, 0)
ops.section('Elastic', 1, 200000000000.0, 0.01, 8.33e-06, 8.33e-06, 80000000000.0, 1e-06)
ops.geomTransf('Linear', 1, 0.0, 0.0, 1.0)
ops.geomTransf('Linear', 2, 1.0, 0.0, 0.0)
ops.element('elasticBeamColumn', 1, 1, 2, 1, 1, '-mass', 0.0)
ops.element('elasticBeamColumn', 2, 2, 3, 1, 1, '-mass', 0.0)
ops.element('elasticBeamColumn', 3, 3, 4, 1, 1, '-mass', 0.0)
ops.element('elasticBeamColumn', 4, 1, 4, 1, 1, '-mass', 0.0)
ops.element('elasticBeamColumn', 5, 2, 4, 1, 2, '-mass', 0.0)

# ── Analysis: case #1 Static 'Static' ──
# Setup and step protocol as the application runs them.
ops.timeSeries('Linear', 1, '-factor', 1.0)
ops.pattern('Plain', 1, 1)
ops.load(4, 0.0, 0.0, -1000.0, 0.0, 0.0, 0.0)
ops.system('BandGeneral')
ops.numberer('RCM')
ops.constraints('Plain')
ops.test('NormDispIncr', 1e-08, 25)
ops.algorithm('Linear')
ops.integrator('LoadControl', 1.0)
ops.analysis('Static')
ops.analyze(1)
ops.reactions()
