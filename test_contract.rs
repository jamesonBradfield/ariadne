#[test]
fn test_new() {
    let entity = Entity::new();
    assert_eq!(entity.health, 100.0);
    assert_eq!(entity.armor, 50.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_heal() {
    let mut entity = Entity::new();
    entity.heal(50.0);
    assert_eq!(entity.health, 100.0);
}

#[test]
fn test_take_damage() {
    let mut entity = Entity::new();
    entity.take_damage(50.0);
    assert_eq!(entity.health, 50.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_take_damage_over_health() {
    let mut entity = Entity::new();
    entity.take_damage(150.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}