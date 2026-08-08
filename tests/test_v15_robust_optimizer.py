import importlib.util, pathlib, sys, unittest
MODULE=pathlib.Path(__file__).resolve().parents[1]/"simulation"/"v15"/"robust_optimizer.py"
spec=importlib.util.spec_from_file_location("v15_robust_optimizer",MODULE);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
def o(name,gain,cov=1.40,sts=1.40,risk=100.0,conc=.50): return m.ScenarioOutcome(name,gain,cov,sts,risk,conc)
def c(name,nominal,no_grad=0,oracle=0,model=0,cost=0,turnover=100,outcomes=None,cls=None,pre_cov=1.4,pre_sts=1.4):
    return m.Candidate(name,cls or m.ActionClass.EXPAND,nominal,no_grad,oracle,model,cost,turnover,pre_cov,pre_sts,100,.5,tuple(outcomes or [o("base",nominal)]))
class T(unittest.TestCase):
    def test_maximin(self):
        g=m.RobustGovernor(m.RegimeLimits(min_robust_gain=.01));a=c("flashy",1,outcomes=[o("b",1),o("s",.01)]);b=c("robust",.4,outcomes=[o("b",.4),o("s",.3)])
        self.assertEqual(g.choose([a,b],m.Mode.GREEN).candidate.name,"robust")
    def test_uncertainty(self):
        g=m.RobustGovernor(m.RegimeLimits(min_robust_gain=.05));x=c("x",.2,oracle=.08,model=.05,cost=.03,outcomes=[o("s",.15)])
        self.assertFalse(g.evaluate(x,m.Mode.GREEN).accepted)
    def test_concentration(self):
        g=m.RobustGovernor(m.RegimeLimits(max_asset_concentration=.8));x=c("x",.5,outcomes=[o("s",.4,cov=1.8,sts=1.7,conc=.91)])
        self.assertEqual(g.evaluate(x,m.Mode.GREEN).reason,"concentration-limit")
    def test_absolute_floor(self):
        g=m.RobustGovernor(m.RegimeLimits(min_risk_assets=10));x=c("x",.1,outcomes=[o("s",.08,cov=10,sts=10,risk=1)])
        self.assertEqual(g.evaluate(x,m.Mode.GREEN).reason,"absolute-risk-capital-floor")
    def test_orange(self): self.assertEqual(m.RobustGovernor(m.RegimeLimits()).evaluate(c("x",.2),m.Mode.ORANGE).reason,"orange-no-expansion")
    def test_red_defense(self):
        g=m.RobustGovernor(m.RegimeLimits(max_defensive_loss=.02));x=c("h",-.01,cls=m.ActionClass.REDUCE,pre_cov=1.01,pre_sts=1.01,outcomes=[o("p",-.01,cov=1.06,sts=1.08)])
        self.assertTrue(g.evaluate(x,m.Mode.RED).accepted);self.assertFalse(g.evaluate(c("e",.5),m.Mode.RED).accepted)
    def test_alpha(self):
        x=c("a",.2,no_grad=-.05);self.assertAlmostEqual(x.initiated_alpha,.2);self.assertAlmostEqual(m.edge_activation_ratio(.2,-.05),1)
        y=c("m",.2,no_grad=.08);self.assertAlmostEqual(y.initiated_alpha,.12);self.assertAlmostEqual(m.edge_activation_ratio(.2,.08),.6)
    def test_turnover_tiebreak(self):
        g=m.RobustGovernor(m.RegimeLimits(min_robust_gain=.01));a=c("lo",.2,turnover=10,outcomes=[o("s",.15)]);b=c("hi",.2,turnover=100,outcomes=[o("s",.15)])
        self.assertEqual(g.choose([b,a],m.Mode.GREEN).candidate.name,"lo")
    def test_capture_efficiency(self): self.assertAlmostEqual(m.capture_efficiency(99,100),.99)
if __name__=="__main__":unittest.main()
