# Gradle example

Two sprints of a small Java library tested with JUnit 5. Method names carry
the sprint id (`S01_fahrenheitToCelsius`) and so do display names
(`@DisplayName("[S02] …")`). On the `s01-regression` branch an S02
"optimisation" breaks the Fahrenheit conversion, and the gate reports
**REGRESSION from sprint S01**.

Needs a JDK 17+. The Gradle wrapper downloads Gradle on first use.
