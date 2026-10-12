// Package shapes is the sprintwarden Go example.
package shapes

import "math"

// Version is reported by the legacy test.
const Version = "1.0.0"

// RectangleArea is sprint S01.
func RectangleArea(w, h float64) float64 { return w * h }

// CircleArea is sprint S01.
func CircleArea(r float64) float64 { return math.Pi * r * r }

// TrianglePerimeter is sprint S02.
func TrianglePerimeter(a, b, c float64) float64 { return a + b + c }

// IsValidTriangle is sprint S02.
func IsValidTriangle(a, b, c float64) bool { return a+b > c && a+c > b && b+c > a }
