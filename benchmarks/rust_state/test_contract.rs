#[test]
fn test_armor_mitigation_and_death() {
    let mut entity = Entity::new();
    entity.take_damage(100.0);
    assert_eq!(entity.health, 50.0);
    assert!(!entity.is_dead);
    
    entity.take_damage(100.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}
