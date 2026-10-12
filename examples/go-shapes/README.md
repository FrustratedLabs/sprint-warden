# Go example

Two sprints of a tiny geometry package. Test names carry the sprint id after
`Test_` (`Test_S01_CircleArea`), and subtests carry it in their name
(`t.Run("S02 perimeter", …)`). On the `s01-regression` branch an S02 cleanup
swaps the circle-area formula, and the gate reports **REGRESSION from sprint S01**.

Needs [go-junit-report](https://github.com/jstemmer/go-junit-report):
`go install github.com/jstemmer/go-junit-report/v2@latest`. `examples/run-all.sh go`
installs it into a temporary directory if it's missing.
