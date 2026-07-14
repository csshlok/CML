package service

import "fmt"

type Service struct{}
func (Service) Execute() { fmt.Println("Vault") }
